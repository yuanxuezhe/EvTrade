"""RPC 三态健康监测测试。

仅覆盖 server/services/rpc_health.py 现有心跳逻辑增加的三态判定，
不新增模块，不重写探测逻辑。

状态协议：
- 0: code=0 且 row_count>0
- 1: 请求队列积压 / 超时 / 通信异常
- 2: 收到应答但 code!=0，或 code=0 但 row_count=0
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from server.api import deps
from server.services import rpc_health


@pytest.fixture(autouse=True)
def _reset_rpc_health_state(monkeypatch):
    monkeypatch.setattr(rpc_health, "_rpc_status", rpc_health.RPC_STATUS_COMM_ERROR)
    monkeypatch.setattr(rpc_health, "_last_ok_at", 0.0)
    monkeypatch.setattr(rpc_health, "_last_err_msg", "")
    monkeypatch.setattr(rpc_health, "_last_queue_depth", 0)
    monkeypatch.setattr(rpc_health, "_last_status_msg", "")


def _asset_response(code=0, rows=None, msg="ok"):
    return {"code": code, "msg": msg, "list": rows if rows is not None else []}


def _normal_asset_row():
    return {
        "cash": 1000.0,
        "frozen_cash": 10.0,
        "market_value": 500.0,
        "total_asset": 1500.0,
    }


def _run(coro):
    return asyncio.run(coro)


def test_probe_queue_backlog_is_status_1_and_skips_request(monkeypatch):
    qry = AsyncMock(return_value=_asset_response(rows=[_normal_asset_row()]))
    broadcast_status = AsyncMock()
    monkeypatch.setattr(rpc_health, "MAX_PENDING", 2)
    monkeypatch.setattr(
        rpc_health,
        "_get_request_queue_depth",
        AsyncMock(return_value=rpc_health.MAX_PENDING),
    )
    monkeypatch.setattr(rpc_health, "qry_asset", qry)
    monkeypatch.setattr(rpc_health, "_broadcast_rpc_status", broadcast_status)

    status = _run(rpc_health._probe_once())

    assert status == rpc_health.RPC_STATUS_COMM_ERROR
    current = rpc_health.get_status()
    assert current["status"] == 1
    assert current["message"] == "RPC通信异常，请检查是否正常启动"
    assert current["request_queue_depth"] == rpc_health.MAX_PENDING
    assert qry.await_count == 0
    # 积压状态: _probe_once 只负责状态判定, 实际广播由 _sync_loop 状态变化时触发
    assert broadcast_status.await_count == 0


def test_probe_timeout_is_status_1(monkeypatch):
    monkeypatch.setattr(rpc_health, "_get_request_queue_depth", AsyncMock(return_value=0))
    monkeypatch.setattr(
        rpc_health,
        "qry_asset",
        AsyncMock(side_effect=asyncio.TimeoutError()),
    )
    monkeypatch.setattr(rpc_health, "_broadcast_rpc_status", AsyncMock())

    status = _run(rpc_health._probe_once())

    assert status == rpc_health.RPC_STATUS_COMM_ERROR
    current = rpc_health.get_status()
    assert current["status"] == 1
    assert "超时" in current["last_err_msg"]


@pytest.mark.parametrize(
    "response",
    [
        _asset_response(code=7, rows=[], msg="broker error"),
        _asset_response(code=0, rows=[], msg="ok"),
    ],
)
def test_probe_abnormal_response_is_status_2(monkeypatch, response):
    monkeypatch.setattr(rpc_health, "_get_request_queue_depth", AsyncMock(return_value=0))
    monkeypatch.setattr(rpc_health, "qry_asset", AsyncMock(return_value=response))
    monkeypatch.setattr(rpc_health, "_broadcast_rpc_status", AsyncMock())

    status = _run(rpc_health._probe_once())

    current = rpc_health.get_status()
    assert status == rpc_health.RPC_STATUS_DATA_ERROR
    assert current["status"] == 2
    assert current["message"] == "RPC通信正常，但没有返回正常数据"


def test_probe_normal_response_is_status_0_and_updates_asset(monkeypatch):
    update_one = MagicMock(return_value=1)
    broadcast_status = AsyncMock()
    monkeypatch.setattr(rpc_health, "_get_request_queue_depth", AsyncMock(return_value=0))
    monkeypatch.setattr(
        rpc_health,
        "qry_asset",
        AsyncMock(return_value=_asset_response(code=0, rows=[_normal_asset_row()])),
    )
    monkeypatch.setattr(rpc_health.Assets, "update_one", update_one)
    monkeypatch.setattr(rpc_health, "_broadcast_rpc_status", broadcast_status)
    monkeypatch.setattr(rpc_health.ws_manager, "broadcast", AsyncMock())

    status = _run(rpc_health._probe_once())

    current = rpc_health.get_status()
    assert status == rpc_health.RPC_STATUS_OK
    assert current["status"] == 0
    assert current["ok"] is True
    assert current["message"] == "RPC通讯正常"
    update_one.assert_called_once()
    # _probe_once 不广播, 由 _sync_loop 状态变化时广播, 这里只断言 helper 未被错误调用
    assert broadcast_status.await_count == 0


def test_only_status_0_passes_trade_guard(monkeypatch):
    for status in (rpc_health.RPC_STATUS_COMM_ERROR, rpc_health.RPC_STATUS_DATA_ERROR):
        monkeypatch.setattr(rpc_health, "_rpc_status", status)
        assert rpc_health.check_ok() is False

    monkeypatch.setattr(rpc_health, "_rpc_status", rpc_health.RPC_STATUS_OK)
    assert rpc_health.check_ok() is True


def test_require_rpc_ok_rejects_nonzero_status(monkeypatch):
    monkeypatch.setattr(deps, "check_ok", lambda: False)
    with pytest.raises(HTTPException) as exc:
        deps.require_rpc_ok()
    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "RPC_COMM_ERROR"
