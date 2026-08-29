"""
strategy_exec.signal.task_progress_publisher — task_progress 实时推送

📌 设计要点:
- 复用 SignalPublisher 的 aio_pika connection / exchange (单连接多 routing_key)
- 复用同一 exchange "strategy.exchange", routing_key 命名空间 "task.progress.*"
- 节流策略 (避免高频 bar 进度刷爆 ws):
    - phase 变化 → 立即推
    - status 变化 → 立即推
    - bar_idx 增量 ≥ 5% 且距上次 ≥ 2s → 推
    - 其他情况 → 跳过
    - status='queued' 或 progress 为空 → 跳过 (与 strategy_exec/api/internal.py run_task 提交语义对齐)
- 失败兜底: best-effort, publish 异常不抛 (写 DB 已经成功, 不应阻塞主流程)

拓扑 (与 server/services/strategy/task_progress_consumer.py 对称):
- exchange: 复用 strategy.exchange (topic, durable=True)
- routing_key: f"task.progress.{task_id}"
- queue: EvTrade.TaskProgress (consumer 端创建, durable=True)
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

from strategy_exec.config import get_settings

log = logging.getLogger(__name__)


# 节流参数 (写在这里而不是 settings — 业务参数, 不走 env)
THROTTLE_MIN_INTERVAL_S = 2.0      # 同 task 两次推送最小间隔
THROTTLE_BAR_PCT = 0.05             # bar_idx 增量阈值 (5%)


def _should_emit(
    task_id: int,
    status: Optional[str],
    progress: Optional[Dict[str, Any]],
    last_emit: Dict[int, Dict[str, Any]],
    now_s: float,
) -> bool:
    """节流判定 — 纯函数, 便于单测

    Args:
        task_id: 策略任务 ID
        status: 新 status (None=不变)
        progress: 新 progress dict (None=无 progress 变化)
        last_emit[task_id]: 上次推送时记录的 {status, phase, bar_idx, ts_s}
        now_s: 当前时间 (秒, time.time())

    Returns:
        True=应推, False=跳过

    规则:
      1. status='queued' → 跳过 (无意义, queued 是预建状态)
      2. status 与上次不同 → 推
      3. progress.phase 与上次不同 → 推
      4. progress 含 bar_idx + total_bars:
           - 增量 ≥ 5% (相对 total_bars) AND 距上次 ≥ 2s → 推
           - 否则跳过
      5. progress 无 bar_idx (e.g. load_script/build_cerebro) → 上一条规则已处理 (phase 变化)
      6. 首次推送 (last_emit[task_id] 不存在) → 推
    """
    # queued 跳过
    if status == "queued":
        return False

    # 首次推送
    prev = last_emit.get(task_id)
    if prev is None:
        return status is not None or progress is not None

    # status 变化
    if status is not None and status != prev.get("status"):
        return True

    # progress 变化
    if progress is None:
        return False

    cur_phase = progress.get("phase")
    if cur_phase is not None and cur_phase != prev.get("phase"):
        return True

    # bar_idx 增量检查
    cur_bar = progress.get("bar_idx")
    cur_total = progress.get("total_bars")
    if cur_bar is not None and cur_total:
        prev_bar = prev.get("bar_idx") or 0
        delta_pct = (float(cur_bar) - float(prev_bar)) / float(cur_total)
        elapsed = now_s - float(prev.get("ts_s") or now_s)
        if delta_pct >= THROTTLE_BAR_PCT and elapsed >= THROTTLE_MIN_INTERVAL_S:
            return True
        return False

    return False


def _record_emit(
    task_id: int,
    status: Optional[str],
    progress: Optional[Dict[str, Any]],
    last_emit: Dict[int, Dict[str, Any]],
    now_s: float,
) -> None:
    """记录本次推送的状态 (供下次节流判定)"""
    snap: Dict[str, Any] = {"ts_s": now_s}
    if status is not None:
        snap["status"] = status
    else:
        snap["status"] = last_emit.get(task_id, {}).get("status")
    if progress is not None:
        snap["phase"] = progress.get("phase")
        if progress.get("bar_idx") is not None:
            snap["bar_idx"] = progress["bar_idx"]
    last_emit[task_id] = snap


class TaskProgressPublisher:
    """task_progress 异步 RabbitMQ publisher, 单例

    与 SignalPublisher 共享同一 aio_pika connection (延迟获取, 无副作用)
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._last_emit: Dict[int, Dict[str, Any]] = {}
        # 复用 SignalPublisher 的 connection / channel / exchange
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def attach_loop(self) -> None:
        """绑定当前 event loop (在 main.py lifespan 启动时调用)"""
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

    def should_emit(
        self,
        task_id: int,
        status: Optional[str],
        progress: Optional[Dict[str, Any]],
    ) -> bool:
        """同步版节流判定 — data_access 层调用, 不进 IO"""
        return _should_emit(task_id, status, progress, self._last_emit, time.time())

    def record_emit(
        self,
        task_id: int,
        status: Optional[str],
        progress: Optional[Dict[str, Any]],
    ) -> None:
        """同步版记录 — data_access 层调用"""
        _record_emit(task_id, status, progress, self._last_emit, time.time())

    async def publish(
        self,
        task_id: int,
        status: Optional[str],
        progress: Optional[Dict[str, Any]],
    ) -> bool:
        """异步 publish (fire-and-forget)

        Returns:
            True=已发出, False=被节流跳过

        Raises:
            不抛异常: 失败仅 log warning (best-effort)
        """
        from datetime import datetime, timezone

        import aio_pika

        from strategy_exec.signal.publisher import get_publisher

        payload: Dict[str, Any] = {
            "type": "task_progress_update",
            "task_id": task_id,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        if status is not None:
            payload["status"] = status
        if progress is not None:
            payload["progress"] = progress

        body = payload
        import json
        body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")

        routing_key = f"task.progress.{task_id}"
        message = aio_pika.Message(
            body=body_bytes,
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )

        try:
            publisher = get_publisher()
            if publisher._exchange is None:  # type: ignore[attr-defined]
                await publisher.connect()
            assert publisher._exchange is not None  # type: ignore[attr-defined]
            await publisher._exchange.publish(  # type: ignore[attr-defined]
                message,
                routing_key=routing_key,
                timeout=get_settings().evtrade_strategy_publish_confirm_timeout,
            )
            log.debug(
                "[task_progress_publisher] task=%d status=%s phase=%s published rk=%s",
                task_id, status, progress.get("phase") if progress else None, routing_key,
            )
            return True
        except Exception as e:
            log.warning(
                "[task_progress_publisher] task=%d publish failed (best-effort, ignored): %s",
                task_id, e,
            )
            return False


# 单例
_publisher: Optional[TaskProgressPublisher] = None


def get_task_progress_publisher() -> TaskProgressPublisher:
    """返单例 (lazy init)"""
    global _publisher
    if _publisher is None:
        _publisher = TaskProgressPublisher()
    return _publisher


async def close_task_progress_publisher() -> None:
    """应用关闭时调用"""
    global _publisher
    _publisher = None


def reset_for_test() -> None:
    """测试用 — 清单例 + 清节流记录"""
    global _publisher
    _publisher = None