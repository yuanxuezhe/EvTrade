"""RPC 三态健康监测测试。

仅覆盖 server/services/rpc_health.py 现有心跳逻辑增加的三态判定，
不新增模块，不重写探测逻辑。

状态协议：
- 0: code=0 且 row_count>0
- 1: 请求队列积压 / 超时 / 通信异常
- 2: 收到应答但 code!=0，或 code=0 但 row_count=0

v2026-08-07: _probe_once() 返回 (success, detail) tuple，不再直接 _set_status。
状态变更由 _sync_loop 根据连续失败次数（>= 3）统一决策。
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


def test_probe_queue_backlog_returns_false(monkeypatch):
    """队列积压 → _probe_once 返回 (False, reason)，不发 qry_asset。"""
    qry = AsyncMock(return_value=_asset_response(rows=[_normal_asset_row()]))
    monkeypatch.setattr(rpc_health, "MAX_PENDING", 2)
    monkeypatch.setattr(
        rpc_health,
        "_get_request_queue_depth",
        AsyncMock(return_value=rpc_health.MAX_PENDING),
    )
    monkeypatch.setattr(rpc_health, "_get_pending_count", AsyncMock(return_value=0))
    monkeypatch.setattr(rpc_health, "qry_asset", qry)

    success, detail = _run(rpc_health._probe_once())

    assert success is False
    assert "积压" in detail
    assert qry.await_count == 0
    # _probe_once 不再直接 _set_status
    assert rpc_health._rpc_status == rpc_health.RPC_STATUS_COMM_ERROR  # 初始值不变


def test_probe_timeout_returns_false(monkeypatch):
    """RPC 超时 → _probe_once 返回 (False, detail)。"""
    monkeypatch.setattr(rpc_health, "_get_request_queue_depth", AsyncMock(return_value=0))
    monkeypatch.setattr(rpc_health, "_get_pending_count", AsyncMock(return_value=0))
    monkeypatch.setattr(
        rpc_health,
        "qry_asset",
        AsyncMock(side_effect=asyncio.TimeoutError()),
    )

    success, detail = _run(rpc_health._probe_once())

    assert success is False
    assert "超时" in detail


@pytest.mark.parametrize(
    "response",
    [
        _asset_response(code=7, rows=[], msg="broker error"),
        _asset_response(code=0, rows=[], msg="ok"),
    ],
)
def test_probe_abnormal_response_returns_false(monkeypatch, response):
    """数据异常 → _probe_once 返回 (False, detail)。"""
    monkeypatch.setattr(rpc_health, "_get_request_queue_depth", AsyncMock(return_value=0))
    monkeypatch.setattr(rpc_health, "_get_pending_count", AsyncMock(return_value=0))
    monkeypatch.setattr(rpc_health, "qry_asset", AsyncMock(return_value=response))

    success, detail = _run(rpc_health._probe_once())

    assert success is False
    assert detail != ""


def test_probe_normal_response_returns_true_and_updates_asset(monkeypatch):
    """正常应答 → _probe_once 返回 (True, "")，写 assets 表。"""
    upsert_one = MagicMock(return_value=True)
    monkeypatch.setattr(rpc_health, "_get_request_queue_depth", AsyncMock(return_value=0))
    monkeypatch.setattr(rpc_health, "_get_pending_count", AsyncMock(return_value=0))
    monkeypatch.setattr(
        rpc_health,
        "qry_asset",
        AsyncMock(return_value=_asset_response(code=0, rows=[_normal_asset_row()])),
    )
    monkeypatch.setattr(rpc_health.Assets, "upsert_one", upsert_one)
    monkeypatch.setattr(rpc_health.ws_manager, "broadcast", AsyncMock())

    success, detail = _run(rpc_health._probe_once())

    assert success is True
    upsert_one.assert_called_once()
    # _probe_once 不再直接 _set_status / broadcast


def test_sync_loop_three_failures_then_recovery(monkeypatch):
    """_sync_loop: 连续 3 次失败才切换状态；1 次成功立即恢复。"""
    monkeypatch.setattr(rpc_health, "_rpc_status", rpc_health.RPC_STATUS_OK)

    probe_mock = AsyncMock(side_effect=[
        (False, "fail1"),
        (False, "fail2"),
        (False, "fail3"),
        (True, ""),       # 第 4 次成功，应该恢复
    ])
    broadcast_mock = AsyncMock()
    asset_mock = AsyncMock()

    monkeypatch.setattr(rpc_health, "_probe_once", probe_mock)
    monkeypatch.setattr(rpc_health, "_broadcast_rpc_status", broadcast_mock)
    monkeypatch.setattr(rpc_health, "_broadcast_asset", asset_mock)
    monkeypatch.setattr(rpc_health, "_CONSECUTIVE_FAILURE_THRESHOLD", 3)

    async def run_four_probes():
        for _ in range(4):
            success, detail = await rpc_health._probe_once()
            if success:
                if rpc_health._rpc_status != rpc_health.RPC_STATUS_OK:
                    rpc_health._set_status(rpc_health.RPC_STATUS_OK)
                    await rpc_health._broadcast_rpc_status()
                await rpc_health._broadcast_asset()
            else:
                rpc_health._consecutive_failures = getattr(rpc_health, "_consecutive_failures", 0) + 1
                if rpc_health._consecutive_failures >= rpc_health._CONSECUTIVE_FAILURE_THRESHOLD:
                    if rpc_health._rpc_status == rpc_health.RPC_STATUS_OK:
                        rpc_health._set_status(
                            rpc_health.RPC_STATUS_COMM_ERROR,
                            err_msg=detail,
                            status_msg=rpc_health._STATUS_TEXT[rpc_health.RPC_STATUS_COMM_ERROR],
                        )
                        await rpc_health._broadcast_rpc_status()

    _run(run_four_probes())

    # 第 3 次失败后应该变异常
    # 第 4 次成功后应该恢复 OK
    assert rpc_health._rpc_status == rpc_health.RPC_STATUS_OK
    # broadcast 被调了 2 次（一次变异常，一次恢复）
    assert broadcast_mock.await_count == 2


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
