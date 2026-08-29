"""
server/tests/services/quote_sync/test_sync.py — sync_one_day 核心单测 (mock broker + repo)

覆盖:
  - 交易日: broker 返 N 根 → upsert + 游标推进
  - 假日: broker 返 0 根 → 成功空, 游标照常推进
  - broker 失败 (BrokerError): 游标不动, 向上抛
  - 无配置行: raise NO_CONFIG
  - 游标单调向前 (同一天重跑不后退)
mock 掉 get_his_hq_client().fetch_one_day + repository.upsert/advance/get, 不碰真 DB/broker。
"""
import pytest

from server.services.quote_sync import sync as sync_mod
from server.services.quote_sync import repository as repo
from server.services.quote_sync.broker import BrokerError


class _FakeRow:
    def __init__(self, **kw):
        self.__dict__.update(kw)


@pytest.mark.asyncio
async def test_sync_one_day_trading_day_advances_cursor(monkeypatch):
    """交易日: broker 返 2 根 → upsert 2 行, 游标推进到当天."""
    monkeypatch.setattr(repo, "get_config",
                        lambda sc: _FakeRow(stock_code=sc, last_loaded_date="20260824"))
    upserted = {}
    monkeypatch.setattr(repo, "upsert_minute_bars",
                        lambda recs: upserted.update(n=len(recs)) or len(recs))
    advanced = []
    monkeypatch.setattr(repo, "advance_cursor",
                        lambda sc, day: advanced.append((sc, day)))

    class _FakeClient:
        async def connect(self): pass
        async def fetch_one_day(self, sc, day):
            return [
                {"stime": "20260825093100", "open": "0.8", "high": "0.9",
                 "low": "0.7", "close": "0.85", "volume": "100", "amount": "85000.0"},
                {"stime": "20260825093200", "open": "0.85", "high": "0.9",
                 "low": "0.8", "close": "0.87", "volume": "200", "amount": "174000.0"},
            ]
    monkeypatch.setattr(sync_mod, "get_his_hq_client", lambda: _FakeClient())

    res = await sync_mod.sync_one_day("159992.SZ", "20260825")
    assert res["ok"] is True
    assert res["bars"] == 2
    assert res["last_loaded_date"] == "20260825"
    assert advanced == [("159992.SZ", "20260825")]
    assert upserted["n"] == 2


@pytest.mark.asyncio
async def test_sync_one_day_holiday_zero_rows_still_advances(monkeypatch):
    """假日: broker 返 0 根 → 成功空, 游标照常推进 (不停在假日)."""
    monkeypatch.setattr(repo, "get_config",
                        lambda sc: _FakeRow(stock_code=sc, last_loaded_date="20260930"))
    monkeypatch.setattr(repo, "upsert_minute_bars", lambda recs: len(recs or []))
    advanced = []
    monkeypatch.setattr(repo, "advance_cursor",
                        lambda sc, day: advanced.append((sc, day)))

    class _FakeClient:
        async def connect(self): pass
        async def fetch_one_day(self, sc, day):
            return []  # 国庆假日
    monkeypatch.setattr(sync_mod, "get_his_hq_client", lambda: _FakeClient())

    res = await sync_mod.sync_one_day("159992.SZ", "20261001")
    assert res["ok"] is True
    assert res["bars"] == 0
    assert res["last_loaded_date"] == "20261001"
    assert advanced == [("159992.SZ", "20261001")]


@pytest.mark.asyncio
async def test_sync_one_day_broker_error_does_not_advance(monkeypatch):
    """broker 失败 → 游标不动, BrokerError 上抛."""
    monkeypatch.setattr(repo, "get_config",
                        lambda sc: _FakeRow(stock_code=sc, last_loaded_date="20260824"))
    advanced = []
    monkeypatch.setattr(repo, "advance_cursor",
                        lambda sc, day: advanced.append((sc, day)))

    class _FakeClient:
        async def connect(self): pass
        async def fetch_one_day(self, sc, day):
            raise BrokerError("his_hq reply timeout")
    monkeypatch.setattr(sync_mod, "get_his_hq_client", lambda: _FakeClient())

    with pytest.raises(BrokerError):
        await sync_mod.sync_one_day("159992.SZ", "20260825")
    assert advanced == []  # 游标没动


@pytest.mark.asyncio
async def test_sync_one_day_no_config_raises(monkeypatch):
    """无配置行 → raise NO_CONFIG (不拉 broker)."""
    monkeypatch.setattr(repo, "get_config", lambda sc: None)

    class _FakeClient:
        async def connect(self): raise AssertionError("不该连 broker")
    monkeypatch.setattr(sync_mod, "get_his_hq_client", lambda: _FakeClient())

    with pytest.raises(BrokerError, match="NO_CONFIG"):
        await sync_mod.sync_one_day("999999.SZ", "20260825")


@pytest.mark.asyncio
async def test_sync_one_day_cursor_monotonic(monkeypatch):
    """同一天重跑 (day <= 现游标) → 游标不后退."""
    monkeypatch.setattr(repo, "get_config",
                        lambda sc: _FakeRow(stock_code=sc, last_loaded_date="20260826"))
    monkeypatch.setattr(repo, "upsert_minute_bars", lambda recs: len(recs or []))
    advanced = []
    monkeypatch.setattr(repo, "advance_cursor",
                        lambda sc, day: advanced.append((sc, day)))

    class _FakeClient:
        async def connect(self): pass
        async def fetch_one_day(self, sc, day):
            return [{"stime": "20260825093100", "open": "0", "high": "0", "low": "0",
                     "close": "0.8", "volume": "100", "amount": "80000"}]
    monkeypatch.setattr(sync_mod, "get_his_hq_client", lambda: _FakeClient())

    # 补 20260825 (早于现游标 20260826) → 不推进
    res = await sync_mod.sync_one_day("159992.SZ", "20260825")
    assert res["last_loaded_date"] == "20260826"  # 保持, 不后退
    assert advanced == []
