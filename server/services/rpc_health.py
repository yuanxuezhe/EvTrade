"""
rpc_health.py — RPC 通信健康监测 + 资金定时同步

职责:
- 维护全局 RPC 三态状态 (0=正常 / 1=通信异常 / 2=数据异常)，供下单等交易端点拦截使用
- 启动后台 task: 每 5 秒从柜台 qry_asset，写入 assets 表，WS 推送前端
- 超时时间 15 秒: 收到应答后开始计算 5 秒间隔；若 15 秒无应答 → 状态 1
- 状态 0 正常下单；状态 1/2 时下单直接拒绝
- 通过 system_update WS 通道同时推送 rpc_status / asset_update 两类事件

使用方:
- place.py: 下单前调 check_ok()
- sys_status.py: 初始化前调 check_ok()
- main.py: 启动/停止后台 task
- asset.py: GET /api/asset 可拿 rpc_status 详情
- AppHeader.vue: 右上角图标根据后端 rpc_status.status 显示绿/红/黄
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from server.rpc.client import qry_asset, get_rpc_client
from server.rpc.transport import MAX_PENDING, QUEUE_REQ
from server.tables import Assets
from server.ws.manager import ws_manager

log = logging.getLogger(__name__)

# ─── 三态状态码 ──────────────────────────────────────────────────────
RPC_STATUS_OK = 0
RPC_STATUS_COMM_ERROR = 1
RPC_STATUS_DATA_ERROR = 2

_STATUS_TEXT = {
    RPC_STATUS_OK: "RPC通讯正常",
    RPC_STATUS_COMM_ERROR: "RPC通信异常，请检查是否正常启动",
    RPC_STATUS_DATA_ERROR: "RPC通信正常，但没有返回正常数据",
}

# ─── 全局状态 ─────────────────────────────────────────────────────────
_rpc_status: int = RPC_STATUS_OK
_last_ok_at: float = 0.0
_last_err_msg: str = ""
_last_status_msg: str = _STATUS_TEXT[RPC_STATUS_OK]
_last_queue_depth: int = 0
_sync_task: Optional[asyncio.Task] = None

# 配置常量
SYNC_INTERVAL_SEC = 5      # 收到应答后等待 5 秒再下次查询
TIMEOUT_SEC = 15            # 单次 RPC 超时 15 秒
_CONSECUTIVE_FAILURE_THRESHOLD = 3  # 连续 3 次失败才切换状态


def check_ok() -> bool:
    """返回当前 RPC 通信是否正常（仅状态 0 为 True）"""
    return _rpc_status == RPC_STATUS_OK


def get_status() -> dict:
    """返回 RPC 通信详情（供 /api/asset / 诊断 / 前端首屏用）"""
    return {
        "ok": check_ok(),
        "status": _rpc_status,
        "message": _STATUS_TEXT.get(_rpc_status, ""),
        "last_status_msg": _last_status_msg,
        "last_ok_at": _last_ok_at,
        "last_err_msg": _last_err_msg,
        "request_queue_depth": _last_queue_depth,
    }


def _set_status(status: int, err_msg: str = "", status_msg: str = "") -> None:
    """内部: 切换三态并记录。"""
    global _rpc_status, _last_err_msg, _last_status_msg
    if status == RPC_STATUS_OK:
        _rpc_status = RPC_STATUS_OK
        _last_err_msg = ""
        _last_status_msg = _STATUS_TEXT[RPC_STATUS_OK]
        return
    _rpc_status = status
    if err_msg:
        _last_err_msg = err_msg
    if status_msg:
        _last_status_msg = status_msg
    elif status in _STATUS_TEXT:
        _last_status_msg = _STATUS_TEXT[status]


# ─── 后台定时同步 ──────────────────────────────────────────────────────

async def _get_pending_count() -> int:
    """获取 RPClient 当前在途（未应答）的 RPC 请求数量。"""
    try:
        rpc = await get_rpc_client()
        return len(getattr(rpc, "pending", {}))
    except Exception:
        return 0


async def _get_request_queue_depth() -> int:
    """取请求队列当前 message_count。失败时返回 0。"""
    try:
        rpc = await get_rpc_client()
        queue = getattr(rpc, "request_queue", None) or getattr(rpc, "req_queue", None)
        if queue is None:
            # base class 没有暴露 request_queue — 通过 channel 重新声明拿消息数
            from server.rpc.transport import QUEUE_REQ
            ch = rpc.channel
            if ch is None:
                return 0
            ok = await ch.declare_queue(QUEUE_REQ, durable=True, passive=True)
            return int(getattr(ok, "message_count", 0) or 0)
        ok = await queue.declare(passive=True) if False else await queue.declare()  # 走默认 declare 拿 message_count
        return int(getattr(ok, "message_count", 0) or 0)
    except Exception as e:
        log.debug("rpc_health queue depth probe failed: %s", e)
        return 0


async def _broadcast_rpc_status() -> None:
    """通过 system_update 通道推送当前 RPC 状态到前端。"""
    payload = {
        "type": "rpc_status",
        "data": get_status(),
    }
    try:
        await ws_manager.broadcast("system_update", payload, trace_id="rpc_status")
    except Exception as e:
        log.debug("rpc_health broadcast failed: %s", e)


async def _broadcast_asset() -> None:
    """推送最新资产数据到前端（仅在探测成功时调用）。"""
    try:
        row = Assets.query_one(id=1)
        if row is not None:
            await ws_manager.broadcast(
                "system_update",
                {
                    "type": "asset_update",
                    "data": {
                        "cash": float(row.cash or 0),
                        "available": float(row.available if hasattr(row, 'available') and row.available is not None else (row.cash or 0)),
                        "frozen_cash": float(row.frozen_cash or 0),
                        "market_value": float(row.market_value or 0),
                        "total_asset": float(row.total_asset or 0),
                        "synced_at": row.synced_at.isoformat() if row.synced_at else None,
                    },
                },
                trace_id="asset_sync",
            )
    except Exception:
        pass


async def _probe_once() -> tuple:
    """单轮探测：积压 → 超时 → 应答解析。返回 (success: bool, detail: str)。

    不再直接调用 _set_status()，状态变更由 _sync_loop 根据连续失败次数统一决策。
    """
    global _last_ok_at, _last_queue_depth

    # 1) 在途请求积压 → 失败，不发 qry_ast（避免雪崩）
    depth = await _get_request_queue_depth()
    _last_queue_depth = depth
    pending_count = await _get_pending_count()
    if pending_count > 0 or depth >= MAX_PENDING:
        reason = f"RPC pending 积压 ({pending_count} in-flight)" if pending_count > 0 else f"RPC 队列积压 ({depth}>={MAX_PENDING})"
        log.warning("rpc_health skip qry_asset: %s", reason)
        return (False, reason)

    # 2) 调 RPC，超时为失败
    start = time.monotonic()
    try:
        data = await asyncio.wait_for(qry_asset(), timeout=TIMEOUT_SEC)
    except asyncio.TimeoutError:
        log.warning("rpc_health sync TIMEOUT after %ss", TIMEOUT_SEC)
        return (False, f"RPC 超时 ({TIMEOUT_SEC}s)")
    except Exception as e:
        log.warning("rpc_health sync error: %s", e)
        return (False, str(e))

    elapsed = time.monotonic() - start
    list_data = data.get("list", []) if isinstance(data, dict) else []
    code = int(data.get("code", -1)) if isinstance(data, dict) else -1
    row_count = len(list_data)

    # 3) 正常应答 + 有数据 → 成功
    if code == 0 and row_count > 0:
        a = list_data[0]
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        try:
            Assets.upsert_one({
                "id": 1,
                "cash": float(a.get("cash", 0) or 0),
                "available": float(a.get("cash", 0) or 0),
                "frozen_cash": float(a.get("frozen_cash", 0) or 0),
                "market_value": float(a.get("market_value", 0) or 0),
                "total_asset": float(a.get("total_asset", 0) or 0),
                "synced_at": now,
                "synced_from": "rpc_sync",
            })
        except Exception as e:
            log.warning("rpc_health assets upsert failed: %s", e)

        _last_ok_at = time.time()
        log.info(
            "rpc_health sync ok: cash=%.2f total=%.2f (%.1fs)",
            a.get("cash", 0), a.get("total_asset", 0), elapsed,
        )
        return (True, "")

    # 4) 应答但数据异常 → 失败
    if code != 0:
        err_msg = (data.get("msg") if isinstance(data, dict) else None) or f"code={code}"
    else:
        err_msg = "code=0 but row_count=0"
    log.warning("rpc_health sync data error: %s", err_msg)
    return (False, err_msg)


async def _sync_loop():
    """无限循环: 每轮 _probe_once → 连续失败 3 次才切换异常 → 一次成功立即恢复。

    探测永不中止（只要进程在跑），状态变更有缓冲：
    - 连续失败 >= 3 次 → 切换为 COMM_ERROR + broadcast
    - 任意一次成功 → 立即恢复 OK + broadcast，计数器清零
    """
    consecutive_failures = 0
    while True:
        try:
            success, detail = await _probe_once()

            if success:
                # 一次成功就立即恢复 OK
                if _rpc_status != RPC_STATUS_OK:
                    _set_status(RPC_STATUS_OK)
                    await _broadcast_rpc_status()
                consecutive_failures = 0
                # 正常时推 asset_update
                await _broadcast_asset()
            else:
                consecutive_failures += 1
                log.warning(
                    "rpc_health probe failed (%d/%d): %s",
                    consecutive_failures, _CONSECUTIVE_FAILURE_THRESHOLD, detail,
                )

                # 达到阈值才标记异常（只弹一次 broadcast）
                if consecutive_failures >= _CONSECUTIVE_FAILURE_THRESHOLD:
                    if _rpc_status == RPC_STATUS_OK:
                        _set_status(
                            RPC_STATUS_COMM_ERROR,
                            err_msg=detail,
                            status_msg=_STATUS_TEXT[RPC_STATUS_COMM_ERROR],
                        )
                        await _broadcast_rpc_status()
                    # 刚达到阈值时，多等一轮，给 broker 恢复时间
                    if consecutive_failures == _CONSECUTIVE_FAILURE_THRESHOLD:
                        await asyncio.sleep(SYNC_INTERVAL_SEC)
        except Exception as e:
            log.warning("rpc_health loop error: %s", e)
        finally:
            await asyncio.sleep(SYNC_INTERVAL_SEC)


# ─── 启动/停止 ─────────────────────────────────────────────────────────

async def start_sync() -> None:
    """启动后台资产同步 + 健康监测 task"""
    global _sync_task
    if _sync_task is not None and not _sync_task.done():
        log.info("rpc_health: sync task already running")
        return
    _sync_task = asyncio.ensure_future(_sync_loop())
    log.info("rpc_health: sync task started (interval=%ds, timeout=%ds)", SYNC_INTERVAL_SEC, TIMEOUT_SEC)


async def stop_sync() -> None:
    """停止后台同步 task"""
    global _sync_task
    if _sync_task is not None:
        _sync_task.cancel()
        try:
            await _sync_task
        except (asyncio.CancelledError, Exception):
            pass
        _sync_task = None
        log.info("rpc_health: sync task stopped")
