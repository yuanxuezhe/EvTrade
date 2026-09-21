"""
server/tests/services/quote_sync/test_sync.py — sync_one_day 核心单测 (mock broker + repo)

操作记录语义 (2026-08-30 用户拍板):
  - 成功 (含假日 0 根): upsert minute_bars → record_success (重算 last_loaded + status=success)
  - 失败 (broker 连不上): record_failure (status=failed + error_msg) → re-raise

mock 掉 get_his_hq_client().fetch_one_day + repository.{upsert,record_success,record_failure,get_config},
不碰真 DB/broker。
"""
import pytest

from server.services.quote_sync import sync as sync_mod
from server.services.quote_sync import repository as repo
from server.services.quote_sync.broker import BrokerError


class _FakeRow:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _fake_client(rows=None, raise_err=None):
    class _C:
        async def connect(self):
            pass

        # change 2026-09-03 unify-his-hq-broker-client: HisHqClient.fetch_bars
        # (start_date, end_date) — 单段 fetch, 代替旧 fetch_one_day(sc, day)
        async def fetch_bars(self, sc, sd, ed, *, fields=None, period="1m"):
            if raise_err:
                raise raise_err
            return rows or []
    return _C()


@pytest.mark.asyncio
async def test_sync_one_day_success_records_and_returns_recalced(monkeypatch):
    """成功: upsert N 行 → record_success 返重算游标 → res.last_loaded=重算值, status=success."""
    monkeypatch.setattr(repo, "get_config",
                        lambda sc: _FakeRow(stock_code=sc, last_loaded_date="20260824"))
    upserted = {}
    monkeypatch.setattr(repo, "upsert_minute_bars",
                        lambda recs: upserted.update(n=len(recs)) or len(recs))
    recorded = {}
    monkeypatch.setattr(repo, "record_success",
                        lambda sc: recorded.update(stock=sc) or "20260825")
    failed = []
    monkeypatch.setattr(repo, "record_failure", lambda sc, msg: failed.append((sc, msg)))

    monkeypatch.setattr(
        sync_mod, "get_his_hq_client",
        lambda: _fake_client([
            {"stime": "20260825093100", "open": "0.8", "high": "0.9", "low": "0.7",
             "close": "0.85", "volume": "100", "amount": "85000.0"},
            {"stime": "20260825093200", "open": "0.85", "high": "0.9", "low": "0.8",
             "close": "0.87", "volume": "200", "amount": "174000.0"},
        ]),
    )

    res = await sync_mod.sync_one_day("159992.SZ", "20260825")
    assert res["ok"] is True
    assert res["bars"] == 2
    assert res["last_loaded_date"] == "20260825"  # = record_success 重算值
    assert recorded == {"stock": "159992.SZ"}
    assert failed == []  # 没记失败
    assert upserted["n"] == 2


@pytest.mark.asyncio
async def test_sync_one_day_holiday_zero_rows_still_success(monkeypatch):
    """假日: broker 0 根 → 仍 success (record_success 调用), bars=0."""
    monkeypatch.setattr(repo, "get_config",
                        lambda sc: _FakeRow(stock_code=sc, last_loaded_date="20260930"))
    monkeypatch.setattr(repo, "upsert_minute_bars", lambda recs: len(recs or []))
    recorded = []
    monkeypatch.setattr(repo, "record_success", lambda sc: recorded.append(sc) or "20261001")
    failed = []
    monkeypatch.setattr(repo, "record_failure", lambda sc, msg: failed.append((sc, msg)))

    monkeypatch.setattr(sync_mod, "get_his_hq_client", lambda: _fake_client([]))

    res = await sync_mod.sync_one_day("159992.SZ", "20261001")
    assert res["ok"] is True
    assert res["bars"] == 0
    assert recorded == ["159992.SZ"]
    assert failed == []


@pytest.mark.asyncio
async def test_sync_one_day_broker_error_records_failure_and_raises(monkeypatch):
    """broker 失败 → record_failure(带原因) + re-raise BrokerError, last_loaded 不动."""
    monkeypatch.setattr(repo, "get_config",
                        lambda sc: _FakeRow(stock_code=sc, last_loaded_date="20260824"))
    monkeypatch.setattr(repo, "upsert_minute_bars", lambda recs: len(recs or []))
    recorded = []
    monkeypatch.setattr(repo, "record_success", lambda sc: recorded.append(sc) or "")
    failed = []
    monkeypatch.setattr(repo, "record_failure", lambda sc, msg: failed.append((sc, msg)))

    monkeypatch.setattr(
        sync_mod, "get_his_hq_client", lambda: _fake_client(raise_err=BrokerError("his_hq reply timeout"))
    )

    with pytest.raises(BrokerError, match="his_hq reply timeout"):
        await sync_mod.sync_one_day("159992.SZ", "20260825")
    assert recorded == []  # 没记成功
    assert len(failed) == 1
    assert failed[0][0] == "159992.SZ"
    assert "his_hq reply timeout" in failed[0][1]  # 原因写进 error_msg


@pytest.mark.asyncio
async def test_sync_one_day_no_config_records_failure_and_raises(monkeypatch):
    """无配置行 → record_failure(NO_CONFIG) + raise, 不连 broker."""
    monkeypatch.setattr(repo, "get_config", lambda sc: None)
    failed = []
    monkeypatch.setattr(repo, "record_failure", lambda sc, msg: failed.append((sc, msg)))

    class _C:
        async def connect(self):
            raise AssertionError("不该连 broker")
    monkeypatch.setattr(sync_mod, "get_his_hq_client", lambda: _C())

    with pytest.raises(BrokerError, match="NO_CONFIG"):
        await sync_mod.sync_one_day("999999.SZ", "20260825")
    assert len(failed) == 1
    assert "NO_CONFIG" in failed[0][1]


@pytest.mark.asyncio
async def test_sync_one_day_unexpected_exception_records_failure(monkeypatch):
    """upsert 阶段抛非 BrokerError 异常 → record_failure(SYNC_ERROR) + 包装 raise."""
    monkeypatch.setattr(repo, "get_config",
                        lambda sc: _FakeRow(stock_code=sc, last_loaded_date="20260824"))
    monkeypatch.setattr(
        repo, "upsert_minute_bars",
        lambda recs: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    failed = []
    monkeypatch.setattr(repo, "record_failure", lambda sc, msg: failed.append((sc, msg)))

    monkeypatch.setattr(
        sync_mod, "get_his_hq_client",
        lambda: _fake_client([{"stime": "20260825093100", "close": "0.8", "volume": "0", "amount": "0"}]),
    )

    with pytest.raises(BrokerError, match="SYNC_ERROR"):
        await sync_mod.sync_one_day("159992.SZ", "20260825")
    assert len(failed) == 1
    assert "db down" in failed[0][1]


# ─────────────── 周末/假日走 broker (方案 B: 拉 broker, 无数据秒回) ───────────────


@pytest.mark.asyncio
async def test_sync_one_day_weekend_calls_broker(monkeypatch):
    """方案 B: 周末也调 broker (broker 端 broker change B END marker / idle 超时秒返).
    不本地提前跳过; broker 返 [] = 成功空, 游标照常推进.
    """
    monkeypatch.setattr(repo, "get_config",
                        lambda sc: _FakeRow(stock_code=sc, last_loaded_date="20260828"))
    upserted = []
    monkeypatch.setattr(repo, "upsert_minute_bars",
                        lambda recs: upserted.append(recs) or len(recs or []))
    recorded = []
    monkeypatch.setattr(repo, "record_success", lambda sc: recorded.append(sc) or "20260828")

    class _C:
        async def connect(self): pass
        async def fetch_bars(self, stock, sd, ed, *, fields=None, period="1m"):
            return []  # 周末 broker 返 [] (END marker / idle)
        async def close(self): pass
    monkeypatch.setattr(sync_mod, "get_his_hq_client", lambda: _C())

    res = await sync_mod.sync_one_day("159992.SZ", "20260829")  # 周六
    assert res["ok"] is True
    assert res["bars"] == 0
    assert upserted == [[]]            # 调了 broker (broker 返 [], upsert 也跑了, 0 行)
    assert recorded == ["159992.SZ"]  # 记了成功
    assert res["last_loaded_date"] == "20260828"  # 数据最大日期不变 (broker 0 行)


# ─────────────── sync_chunk (change 2026-09-04 quote-sync-chunk-days) ───────────────


@pytest.mark.asyncio
async def test_sync_chunk_uses_default_chunk_days_from_sysconfig(monkeypatch):
    """sync_chunk 不传 chunk_days 时, 从 sys_config.quote_sync_chunk_days 读默认 (10)."""
    monkeypatch.setattr(sync_mod, "get_his_hq_client",
                        lambda: _fake_client(rows=[{"stime": "20240101093100", "open": "0.5"}]))
    monkeypatch.setattr("server.services.quote_sync.sync.repo.get_config",
                        lambda sc: _FakeRow(stock_code=sc, last_loaded_date="20231231"))
    monkeypatch.setattr("server.services.quote_sync.sync.repo.upsert_minute_bars",
                        lambda recs: len(recs or []))
    monkeypatch.setattr("server.services.quote_sync.sync.repo.record_success",
                        lambda sc: "20240120")

    # mock sysconfig.get
    fake_sysconfig = {"quote_sync_chunk_days": 5}
    def _fake_get(key, default=None, user="0"):
        return fake_sysconfig.get(key, default)
    monkeypatch.setattr("server.services.sysconfig.get", _fake_get)

    # 区间 1 月 1 日 ~ 1 月 20 日 (20 天), chunk_days=5 → 应跑 4 批 (5+5+5+5)
    res = await sync_mod.sync_chunk("159992.SZ", "20240101", "20240120")
    assert res["ok"] is True
    assert res["days"] == 20
    assert res["total_bars"] == 20  # 每天 1 根 mock
    assert res["failed_day"] is None


@pytest.mark.asyncio
async def test_sync_chunk_invalid_range_raises(monkeypatch):
    """start > end → BrokerError INVALID_RANGE."""
    monkeypatch.setattr("server.services.quote_sync.sync.repo.get_config",
                        lambda sc: _FakeRow(stock_code=sc))
    with pytest.raises(sync_mod.BrokerError, match="INVALID_RANGE"):
        await sync_mod.sync_chunk("X", "20240110", "20240101", chunk_days=3)


@pytest.mark.asyncio
async def test_sync_chunk_partial_failure_returns_failed_day(monkeypatch):
    """一批内某天 broker 失败 → failed_day 设值, 但 days 仍算成功天."""
    # 让 day=20240105 抛 BrokerError, 其它天返 mock 数据
    def _raise_on_target(sc, sd, ed, *, fields=None, period="1m"):
        if sd == "20240105":
            raise sync_mod.BrokerError("broker 失败 20240105")
        return [{"stime": f"{sd}093100", "open": "0.5"}]

    class _C:
        async def connect(self): pass
        async def fetch_bars(self, sc, sd, ed, *, fields=None, period="1m"):
            return _raise_on_target(sc, sd, ed, fields=fields, period=period)
        async def close(self): pass

    monkeypatch.setattr(sync_mod, "get_his_hq_client", lambda: _C())
    monkeypatch.setattr("server.services.quote_sync.sync.repo.get_config",
                        lambda sc: _FakeRow(stock_code=sc, last_loaded_date="20240101"))
    monkeypatch.setattr("server.services.quote_sync.sync.repo.upsert_minute_bars",
                        lambda recs: len(recs or []))
    monkeypatch.setattr("server.services.quote_sync.sync.repo.record_success",
                        lambda sc: "20240110")
    monkeypatch.setattr("server.services.quote_sync.sync.repo.record_failure",
                        lambda sc, msg: None)

    res = await sync_mod.sync_chunk("159992.SZ", "20240101", "20240110", chunk_days=3)
    # 第一批 1~3 成功 3 天, 20240105 失败 (下一批起点), 5~7/8~10
    assert res["failed_day"] == "20240105"
    assert res["ok"] is False
    assert res["days"] >= 3  # 至少 1~3 成功


@pytest.mark.asyncio
async def test_sync_chunk_all_failed_raises(monkeypatch):
    """第一天就失败 → 抛 BrokerError (跟单日语义一致)."""
    class _C:
        async def connect(self): pass
        async def fetch_bars(self, sc, sd, ed, *, fields=None, period="1m"):
            raise sync_mod.BrokerError("all fail")
        async def close(self): pass

    monkeypatch.setattr(sync_mod, "get_his_hq_client", lambda: _C())
    monkeypatch.setattr("server.services.quote_sync.sync.repo.get_config",
                        lambda sc: _FakeRow(stock_code=sc, last_loaded_date="20240101"))
    monkeypatch.setattr("server.services.quote_sync.sync.repo.record_failure",
                        lambda sc, msg: None)

    with pytest.raises(sync_mod.BrokerError, match="chunk 全部失败"):
        await sync_mod.sync_chunk("159992.SZ", "20240101", "20240105", chunk_days=2)
