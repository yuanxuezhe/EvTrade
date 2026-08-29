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

        async def fetch_one_day(self, sc, day):
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
