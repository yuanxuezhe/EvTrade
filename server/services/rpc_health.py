"""
rpc_health.py — RPC 通信健康监测 + 资金定时同步

职责:
- 维护全局 rpc_ok 状态 (True/False)
- 启动后台 task: 每 5 秒从柜台 qry_asset，写入 assets 表，WS 推送前端
- 超时时间 15 秒: 收到应答后开始计算 5 秒间隔；若 15 秒无应答 → rpc_ok=False
- rpc_ok=False 时: 下单直接拒绝，初始化不允许切日
- rpc_ok=True 时: 正常下单

使用方:
- place.py: 下单前调 check_ok()
- sys_status.py: 初始化前调 check_ok()
- main.py: 启动/停止后台 task
- asset.py: GET /api/asset 可以返回 rpc_ok 状态
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from server.rpc.client import qry_asset, get_rpc_client
from server.rpc.transport import MAX_PENDING
from server.tables import Assets
from server.ws.manager import ws_manager

log = logging.getLogger(__name__)

# ─── 全局状态 ──────────────────────────────────────────────────────────

_rpc_ok: bool = True
_last_ok_at: float = 0.0
_last_err_msg: str = ""
_sync_task: Optional[asyncio.Task] = None

# 配置常量
SYNC_INTERVAL_SEC = 5      # 收到应答后等待 5 秒再下次查询
TIMEOUT_SEC = 15            # 单次 RPC 超时 15 秒


def check_ok() -> bool:
    """返回当前 RPC 通信是否正常"""
    return _rpc_ok


def get_status() -> dict:
    """返回 RPC 通信详情（供 /api/asset / 诊断用）"""
    return {
        "ok": _rpc_ok,
        "last_ok_at": _last_ok_at,
        "last_err_msg": _last_err_msg,
    }


# ─── 后台定时同步 ──────────────────────────────────────────────────────

async def _sync_loop():
    """无限循环: 每轮 qry_asset → 写 DB → WS 推送 → 等 5 秒"""
    global _rpc_ok, _last_ok_at, _last_err_msg

    while True:
        try:
            # v100: 队列深度先检 — 积压时直接判 RPC 不通 + 跳过本轮,
            #   避免每次 15s timeout 浪费 + 自己又把 pending 队列填满
            #   (broker 端无应答时, sync_loop 自己也是 pending 占用方之一)
            try:
                rpc = await get_rpc_client()
                pending_count = len(rpc.pending)
            except Exception:
                pending_count = 0  # 取不到时不阻塞同步
            if pending_count >= MAX_PENDING:
                _rpc_ok = False
                _last_err_msg = f"RPC 队列积压 ({pending_count}>={MAX_PENDING})"
                log.warning("rpc_health skip qry_asset: %s", _last_err_msg)
                await asyncio.sleep(SYNC_INTERVAL_SEC)
                continue

            start = time.monotonic()
            data = await asyncio.wait_for(qry_asset(), timeout=TIMEOUT_SEC)

            elapsed = time.monotonic() - start
            list_data = data.get("list", []) if isinstance(data, dict) else []
            code = int(data.get("code", -1)) if isinstance(data, dict) else -1

            if code == 0 and list_data:
                a = list_data[0]
                now = datetime.now(timezone.utc).replace(tzinfo=None)

                # 写入 assets 表 (单行, id=1)
                Assets.update_one({
                    "id": 1,
                    "cash": float(a.get("cash", 0) or 0),
                    "frozen_cash": float(a.get("frozen_cash", 0) or 0),
                    "market_value": float(a.get("market_value", 0) or 0),
                    "total_asset": float(a.get("total_asset", 0) or 0),
                    "synced_at": now,
                    "synced_from": "rpc_sync",
                }, id=1)

                _rpc_ok = True
                _last_ok_at = time.time()
                _last_err_msg = ""

                # WS 推送前端 (走 system_update 频道, type=asset_update)
                try:
                    await ws_manager.broadcast(
                        "system_update",
                        {
                            "type": "asset_update",
                            "data": {
                                "cash": float(a.get("cash", 0) or 0),
                                "frozen_cash": float(a.get("frozen_cash", 0) or 0),
                                "market_value": float(a.get("market_value", 0) or 0),
                                "total_asset": float(a.get("total_asset", 0) or 0),
                                "synced_at": now.isoformat(),
                            },
                        },
                        trace_id="asset_sync",
                    )
                except Exception:
                    pass  # WS 推送失败不影响状态

                log.info(
                    "rpc_health sync ok: cash=%.2f total=%.2f (%.1fs)",
                    a.get("cash", 0), a.get("total_asset", 0), elapsed,
                )
            else:
                # code != 0 视为异常
                msg = data.get("msg", f"code={code}") if isinstance(data, dict) else "invalid response"
                _rpc_ok = False
                _last_err_msg = msg
                log.warning("rpc_health sync code!=0: %s", msg)

        except asyncio.TimeoutError:
            _rpc_ok = False
            _last_err_msg = f"RPC 超时 ({TIMEOUT_SEC}s)"
            log.warning("rpc_health sync TIMEOUT after %ss", TIMEOUT_SEC)
        except Exception as e:
            _rpc_ok = False
            _last_err_msg = str(e)
            log.warning("rpc_health sync error: %s", e)

        # 等待下一轮 (收到应答后开始计算 5 秒)
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
    if _sync_task is not None and not _sync_task.done():
        _sync_task.cancel()
        try:
            await _sync_task
        except (asyncio.CancelledError, Exception):
            pass
        _sync_task = None
        log.info("rpc_health: sync task stopped")
