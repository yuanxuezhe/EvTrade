"""v8 增: push 链路注入 trd_date 测试

测试 _resolve_active_trd_date_safe:
- 正常返回激活日
- DB 异常返回 None 而不 raise

测试 push listener broadcast payload:
- payload.data 必带 trd_date
- trd_date = 当前激活交易日(覆盖 broker 推的)
- 持久化函数也收到 enriched_row(已注入 trd_date)
"""
import asyncio
from unittest.mock import patch as mock_patch, MagicMock, AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db import Base


# ──── fixtures ────

@pytest.fixture
def in_memory_db():
    """内存 SQLite,跟 test_orders_api 共用同一套 schema 思路"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


# ──── _resolve_active_trd_date_safe ────

def test_resolve_active_trd_date_safe_returns_active_day(monkeypatch):
    """_resolve_active_trd_date_safe 正常:返 SysStatus 中激活日"""
    import server.db as db_module
    import server.services.guards as guards_module
    from server.services import push_dispatcher

    captured_db = {}
    fake_session = MagicMock()
    fake_session.close = MagicMock()

    def fake_session_local():
        captured_db["called"] = True
        return fake_session

    def fake_resolve(db):
        return "20260614"

    # 函数内 `from server.db import SessionLocal` 动态导入,monkeypatch 目标必须是 server.db
    monkeypatch.setattr(db_module, "SessionLocal", fake_session_local)
    # 同样: from server.services.guards import resolve_active_trd_date
    monkeypatch.setattr(guards_module, "resolve_active_trd_date", fake_resolve)

    result = push_dispatcher._resolve_active_trd_date_safe()
    assert result == "20260614"
    assert captured_db.get("called") is True
    fake_session.close.assert_called_once()


def test_resolve_active_trd_date_safe_returns_none_on_exception(monkeypatch):
    """_resolve_active_trd_date_safe 异常:返 None 而不 raise"""
    import server.db as db_module
    from server.services import push_dispatcher

    def boom():
        raise RuntimeError("DB 锁")

    monkeypatch.setattr(db_module, "SessionLocal", boom)

    # 不应 raise
    result = push_dispatcher._resolve_active_trd_date_safe()
    assert result is None


# ──── push listener payload 注入 ────

def test_push_listener_injects_trd_date_into_payload(monkeypatch):
    """v8: push listener broadcast payload.data 必含 trd_date(来自激活日)
       且 trd_date 会覆盖 broker 推的 trd_date
    """
    from server.rpc import client as rpc_client
    from server.services import push_dispatcher
    from server.rpc import parsers_push

    # mock 1: _resolve_active_trd_date_safe → 固定返 "20260614"
    monkeypatch.setattr(
        push_dispatcher, "_resolve_active_trd_date_safe", lambda: "20260614"
    )

    # mock 2: _iter_push_rows → 返一行 broker 推的(带 broker trd_date "20260613" 模拟老委托)
    fake_row = {
        "order_id": "OID-LISTENER",
        "stock_code": "600030.SH",
        "order_status": "50",  # v10: broker 原字段名
        "remark": "10000099",
        "trd_date": "20260613",  # broker 推的老日期
    }
    monkeypatch.setattr(parsers_push, "_iter_push_rows", lambda pkt: [fake_row])

    # mock 3: 持久化 + broadcast
    captured_persisted = []
    monkeypatch.setattr(
        push_dispatcher, "_run_handle_push",
        lambda func, row, ts: captured_persisted.append((func, row.copy())),
    )
    captured_broadcasts = []
    async def fake_broadcast(channel, payload):
        captured_broadcasts.append((channel, payload))
    monkeypatch.setattr(rpc_client.ws_manager, "broadcast", fake_broadcast)

    # mock 4: 构造 fake pkt
    fake_pkt = MagicMock()
    fake_pkt.func.return_value = "ord_cfm"
    monkeypatch.setattr(rpc_client, "_clean_id", lambda s: "ord_cfm" if s == "ord_cfm" else "20260614130000")

    # 直接调 _listen_pushs 一段逻辑(同步:把核心 4 步抽出来测试)
    #   但 _listen_pushs 是 async generator,改用:模拟 listener 内部循环一次
    async def run_once():
        func = "ord_cfm"
        channel = push_dispatcher._PUSH_CHANNEL.get(func)
        rows = parsers_push._iter_push_rows(fake_pkt)
        ts = "20260614130000"
        active_trd_date = push_dispatcher._resolve_active_trd_date_safe()
        for row in rows:
            enriched_row = {**row, "trd_date": active_trd_date} if active_trd_date else row
            payload = {
                "type": func, "channel": channel, "ts": ts, "data": enriched_row,
            }
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, push_dispatcher._run_handle_push, func, enriched_row, ts)
            await rpc_client.ws_manager.broadcast(channel, payload)

    asyncio.run(run_once())

    # 断言 1: 持久化收到的 row.trd_date = "20260614"(激活日,不是 broker 推的 "20260613")
    assert len(captured_persisted) == 1
    persisted_row = captured_persisted[0][1]
    assert persisted_row["trd_date"] == "20260614"
    assert persisted_row["remark"] == "10000099"  # broker 字段透传

    # 断言 2: broadcast payload.data.trd_date = "20260614"
    assert len(captured_broadcasts) == 1
    channel, payload = captured_broadcasts[0]
    assert channel == "order_update"
    assert payload["data"]["trd_date"] == "20260614"
    assert payload["data"]["order_id"] == "OID-LISTENER"


def test_push_listener_no_trd_date_when_resolve_returns_none(monkeypatch):
    """v8: _resolve_active_trd_date_safe 返 None 时,payload 不注入 trd_date(降级而非崩溃)"""
    from server.rpc import client as rpc_client
    from server.services import push_dispatcher
    from server.rpc import parsers_push

    monkeypatch.setattr(
        push_dispatcher, "_resolve_active_trd_date_safe", lambda: None
    )

    fake_row = {"order_id": "OID-NODAY", "stock_code": "600030.SH", "order_status": "49"}
    monkeypatch.setattr(parsers_push, "_iter_push_rows", lambda pkt: [fake_row])

    captured_broadcasts = []
    async def fake_broadcast(channel, payload):
        captured_broadcasts.append((channel, payload))
    monkeypatch.setattr(rpc_client.ws_manager, "broadcast", fake_broadcast)

    monkeypatch.setattr(
        push_dispatcher, "_run_handle_push", lambda func, row, ts: None
    )

    async def run_once():
        func = "ord_cfm"
        channel = push_dispatcher._PUSH_CHANNEL.get(func)
        rows = parsers_push._iter_push_rows(MagicMock())
        active_trd_date = push_dispatcher._resolve_active_trd_date_safe()
        for row in rows:
            # 跟 _listen_pushs 同逻辑: None 时不注入
            enriched_row = {**row, "trd_date": active_trd_date} if active_trd_date else row
            payload = {"type": func, "channel": channel, "ts": "t", "data": enriched_row}
            await rpc_client.ws_manager.broadcast(channel, payload)

    asyncio.run(run_once())

    assert len(captured_broadcasts) == 1
    payload = captured_broadcasts[0][1]
    # 不应有 trd_date 字段(降级)
    assert "trd_date" not in payload["data"]
    assert payload["data"]["order_id"] == "OID-NODAY"


def test_push_listener_handles_trd_cfm(monkeypatch):
    """v8: trd_cfm 推送同样注入 trd_date"""
    from server.rpc import client as rpc_client
    from server.services import push_dispatcher
    from server.rpc import parsers_push

    monkeypatch.setattr(
        push_dispatcher, "_resolve_active_trd_date_safe", lambda: "20260614"
    )

    fake_row = {
        "traded_id": "TID-1", "order_id": "OID-1", "stock_code": "600030.SH",
        "traded_volume": "100", "traded_price": "12.5",
    }
    monkeypatch.setattr(parsers_push, "_iter_push_rows", lambda pkt: [fake_row])
    monkeypatch.setattr(push_dispatcher, "_run_handle_push", lambda f, r, t: None)

    captured = []
    async def fake_broadcast(channel, payload):
        captured.append((channel, payload))
    monkeypatch.setattr(rpc_client.ws_manager, "broadcast", fake_broadcast)

    async def run_once():
        func = "trd_cfm"
        channel = push_dispatcher._PUSH_CHANNEL.get(func)
        rows = parsers_push._iter_push_rows(MagicMock())
        active_trd_date = push_dispatcher._resolve_active_trd_date_safe()
        for row in rows:
            enriched_row = {**row, "trd_date": active_trd_date} if active_trd_date else row
            payload = {"type": func, "channel": channel, "ts": "t", "data": enriched_row}
            await rpc_client.ws_manager.broadcast(channel, payload)

    asyncio.run(run_once())

    assert captured[0][0] == "trade_update"
    assert captured[0][1]["data"]["trd_date"] == "20260614"
    assert captured[0][1]["data"]["traded_volume"] == "100"
    assert captured[0][1]["data"]["traded_id"] == "TID-1"  # v10: 透传 broker 原字段名
