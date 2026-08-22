"""
crawler/runner.py — 同步循环主控

职责:
- 遍历 all_codes 列表
- 调 eastmoney.fetch_base_info() 拉取单只股票信息(仅 3 字段)
- 调 repo.stocks.upsert() 增量入库
- 通过 progress_callback 推送进度(由 sync_manager 注入 WS broadcast)

设计原则:
- 单线程 + sleep 0.5s/只(防反爬)
- 单只失败 → 跳过 + 计入 failed,不影响后续
- 支持 asyncio.Event 优雅停止信号
"""
import asyncio
import time
from typing import Callable, List, Optional

from server.crawler.sources import eastmoney
from server.db import SessionLocal
from server.repo import stocks as stocks_repo


# 防反爬:sleep 0.5s/只
DEFAULT_SLEEP_SEC = 0.5
# 单只 HTTP 超时
DEFAULT_TIMEOUT_SEC = 10.0


async def run(
    all_codes: List[str],
    progress_callback: Callable[[dict], None],
    stop_event: asyncio.Event,
    sleep_sec: float = DEFAULT_SLEEP_SEC,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
):
    """同步循环

    Args:
        all_codes: 待同步股票代码列表,如 ['000001.SZ', '000002.SZ', ...]
        progress_callback: 每只处理完调一次,接 dict 含 processed/inserted/updated/skipped/failed/current_code/...
        stop_event: asyncio.Event,set() 后完成当前只后停止
        sleep_sec: 每只间隔
        timeout_sec: 单只 HTTP 超时
    """
    total = len(all_codes)
    counters = {
        "total": total,
        "processed": 0,
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "failed": 0,
    }
    started_at = time.time()

    for idx, stock_code in enumerate(all_codes):
        # 优雅停止:每只开始前检查
        if stop_event.is_set():
            counters["state"] = "stopped"
            progress_callback({**counters, "current_code": None, "current_name": None,
                               "elapsed_s": time.time() - started_at, "eta_s": 0})
            return counters

        # 拉取(eastmoney.fetch_base_info 是同步函数,to_thread 转异步)
        try:
            data = await asyncio.to_thread(eastmoney.fetch_base_info, stock_code, timeout_sec)
        except Exception as e:
            print(f"[runner] {stock_code} unhandled error: {e}", flush=True)
            data = None

        # 入库
        action = "failed"
        stock_name = ""
        if data is not None:
            stock_name = data.get("stock_name", "")
            db = SessionLocal()
            try:
                action = stocks_repo.upsert(db, stock_code, data)
            except Exception as e:
                print(f"[runner] {stock_code} upsert error: {e}", flush=True)
                action = "failed"
            finally:
                db.close()

        # 计数
        counters["processed"] += 1
        if action == "inserted":
            counters["inserted"] += 1
        elif action == "updated":
            counters["updated"] += 1
        elif action == "skipped":
            counters["skipped"] += 1
        else:
            counters["failed"] += 1

        # ETA 计算
        elapsed = time.time() - started_at
        eta = (elapsed / max(counters["processed"], 1)) * (total - counters["processed"])

        # 推送进度(1Hz 节流 — 但为了简化,每只推一次)
        progress_callback({
            **counters,
            "state": "running",
            "current_code": stock_code,
            "current_name": stock_name,
            "elapsed_s": round(elapsed, 1),
            "eta_s": round(eta, 1),
        })

        # 不推 stock_synced WS 事件 (前端 IndexedDB 负责缓存, 后端不推单只同步事件)

        # 防反爬 sleep
        await asyncio.sleep(sleep_sec)

    # 完成
    counters["state"] = "done"
    progress_callback({**counters, "current_code": None, "current_name": None,
                       "elapsed_s": time.time() - started_at, "eta_s": 0})
    return counters