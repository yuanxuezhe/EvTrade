"""
services/sync/manager.py - 同步任务全局管理器

职责:
- 全局单例 current_task (任何时刻最多 1 个同步任务跑)
- start(): 创建 asyncio.Task,跑 crawler.runner
- stop(): set stop_event,task 优雅退出
- status(): 返 current_task.to_dict()

WS 推送:
- runner 通过 progress_callback 推 stock_sync_progress (每只推一次)
- 广播到 ws_manager.active_connections['sync_update']
- 不推 stock_synced 单只推送 (前端 IndexedDB 负责缓存, 后端不推)
"""
import asyncio
import json
import time
from typing import List, Optional

from server.crawler import runner as crawler_runner
from server.services.sync.task import SyncTask
from server.ws.manager import ws_manager


class SyncManager:
    """全局单例同步任务管理器"""

    def __init__(self):
        self.current_task: Optional[SyncTask] = None
        self._lock = asyncio.Lock()  # 防止并发 start

    async def start(self, all_codes: List[str]) -> SyncTask:
        """启动同步任务

        Returns:
            SyncTask(已启动)

        Raises:
            RuntimeError: 已有任务在跑
        """
        async with self._lock:
            if self.current_task is not None and self.current_task.is_running():
                raise RuntimeError(
                    f"已有同步任务在跑: job_id={self.current_task.job_id}, "
                    f"processed={self.current_task.counters.get('processed', 0)}"
                )
            # 创建新任务
            task = SyncTask()
            task.state = "running"
            task.started_at = time.time()
            task.counters["total"] = len(all_codes)
            task._stop_event = asyncio.Event()
            task._task = asyncio.ensure_future(self._run(task, all_codes))
            self.current_task = task
            return task

    async def _run(self, task: SyncTask, all_codes: List[str]):
        """后台执行:跑 crawler runner + WS broadcast"""
        try:
            # progress callback -> 更新 task 状态 + 推 WS
            def progress_callback(msg: dict):
                # 进度消息 - 更新 task + 推 WS
                task.state = msg.get("state", task.state)
                task.current_code = msg.get("current_code")
                task.current_name = msg.get("current_name")
                task.elapsed_s = msg.get("elapsed_s", 0)
                task.eta_s = msg.get("eta_s", 0)
                if "total" in msg:
                    task.counters["total"] = msg["total"]
                if "processed" in msg:
                    task.counters["processed"] = msg["processed"]
                if "inserted" in msg:
                    task.counters["inserted"] = msg["inserted"]
                if "updated" in msg:
                    task.counters["updated"] = msg["updated"]
                if "skipped" in msg:
                    task.counters["skipped"] = msg["skipped"]
                if "failed" in msg:
                    task.counters["failed"] = msg["failed"]
                # 推 WS
                asyncio.ensure_future(self._broadcast_progress(msg, task))

            await crawler_runner.run(
                all_codes=all_codes,
                progress_callback=progress_callback,
                stop_event=task._stop_event,
            )
        except Exception as e:
            task.state = "failed"
            task.error_message = str(e)
            print(f"[sync_manager] task {task.job_id} failed: {e}", flush=True)
            await self._broadcast_progress({
                "type": "stock_sync_progress",
                "state": "failed",
                "error_message": str(e),
            }, task)

    async def _broadcast_progress(self, msg: dict, task: SyncTask):
        """广播 stock_sync_progress 到 sync_update 频道"""
        payload = {
            "type": "stock_sync_progress",
            "job_id": task.job_id,
            "state": msg.get("state", task.state),
            "total": msg.get("total", task.counters.get("total", 0)),
            "processed": msg.get("processed", task.counters.get("processed", 0)),
            "inserted": msg.get("inserted", task.counters.get("inserted", 0)),
            "updated": msg.get("updated", task.counters.get("updated", 0)),
            "skipped": msg.get("skipped", task.counters.get("skipped", 0)),
            "failed": msg.get("failed", task.counters.get("failed", 0)),
            "current_code": msg.get("current_code"),
            "current_name": msg.get("current_name"),
            "elapsed_s": msg.get("elapsed_s", task.elapsed_s),
            "eta_s": msg.get("eta_s", task.eta_s),
            "ts": time.time(),
        }
        # 用 ws_manager.broadcast 推 sync_update 频道
        try:
            await ws_manager.broadcast("sync_update", payload)
        except Exception as e:
            print(f"[sync_manager] broadcast progress error: {e}", flush=True)

    async def stop(self) -> bool:
        """请求停止当前任务"""
        if self.current_task is None or not self.current_task.is_running():
            return False
        if self.current_task._stop_event:
            self.current_task._stop_event.set()
        return True

    def status(self) -> Optional[dict]:
        """返当前任务状态字典,无任务返 None"""
        if self.current_task is None:
            return None
        # 实时更新 elapsed(若 running)
        if self.current_task.is_running() and self.current_task.started_at:
            self.current_task.elapsed_s = time.time() - self.current_task.started_at
        return self.current_task.to_dict()


# 全局单例
sync_manager = SyncManager()
