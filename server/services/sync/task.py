"""
services/sync/task.py — 单次同步任务

封装:
- job_id (UUID)
- state (idle/running/done/stopped/failed)
- counters (processed/inserted/updated/skipped/failed/total)
- asyncio.Task + stop_event
- timing (started_at/elapsed_s)
"""
import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class SyncTask:
    """单次同步任务状态(REQ-STOCK-003)"""
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state: str = "idle"       # idle / running / done / stopped / failed
    counters: Dict = field(default_factory=lambda: {
        "total": 0, "processed": 0, "inserted": 0, "updated": 0, "skipped": 0, "failed": 0
    })
    current_code: Optional[str] = None
    current_name: Optional[str] = None
    started_at: Optional[float] = None
    elapsed_s: float = 0.0
    eta_s: float = 0.0
    error_message: str = ""

    # 内部 asyncio 句柄(不暴露给 API 序列化)
    _task: Optional[asyncio.Task] = None
    _stop_event: Optional[asyncio.Event] = None

    def is_running(self) -> bool:
        return self.state == "running"

    def to_dict(self) -> Dict:
        """API 返回格式"""
        return {
            "job_id": self.job_id,
            "state": self.state,
            "total": self.counters.get("total", 0),
            "processed": self.counters.get("processed", 0),
            "inserted": self.counters.get("inserted", 0),
            "updated": self.counters.get("updated", 0),
            "skipped": self.counters.get("skipped", 0),
            "failed": self.counters.get("failed", 0),
            "current_code": self.current_code,
            "current_name": self.current_name,
            "elapsed_s": round(self.elapsed_s, 1),
            "eta_s": round(self.eta_s, 1),
            "error_message": self.error_message,
        }