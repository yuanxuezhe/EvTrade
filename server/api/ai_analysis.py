"""
ai_analysis.py - AI 分析 API（invest-analyst skill 集成）

[PoC 同步版] 用户点按钮 → 后端 subprocess 跑
  python3 ~/.hermes/skills/finance/invest-analyst/scripts/invest_analyst_demo.py
→ 解析 stdout JSON → 返回给前端表格。

链路：
  POST /api/ai-analysis  →  调 hermes agent（未来）  →  调 demo 脚本  →  解析 JSON
当前版本：直接调 demo 脚本（hermes 本机，未来包成 hermes 工具）。

入参：
  stock_code   str   "159992.SZ"
  periods      list  ["1d","4h","1h","30m"]   默认 ["1d"]
  start_date   str   "20240813"
  end_date     str   "20260812"

返参：
  {
    "code": 0,
    "msg": "",
    "report": <完整 demo JSON 输出>,
    "table_rows": [
      {"period": "1d", "score": 0.770, "action": "BUY", "confidence": 0.54,
       "entry": 0.919, "stop": 0.823, "tp": 1.063, "rr": 1.5,
       "ema89": 0.83, "macd_hist": 0.0053, "rsi": 62.6, "kdj_k": 75.0},
      ...
    ],
    "synthesis": {...},
    "elapsed_sec": 178.4,
  }
"""
import json
import logging
import os
import re
import subprocess
import time
import asyncio  # ai_analysis 走 asyncio.to_thread 防 event loop 阻塞
from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field, root_validator

logger = logging.getLogger(__name__)

router = APIRouter()

# ============================================================
# demo 脚本路径
# ============================================================
# 绝对路径 — demo 脚本在 hermes skill 目录下，不在 EvTrade 项目内
_DEMO_SCRIPT = os.path.normpath(os.path.expanduser(
    "~/.hermes/skills/finance/invest-analyst/scripts/invest_analyst_demo.py"
))

# 允许的周期 (跟 demo 脚本 ALL_PERIODS 同步)
ALLOWED_PERIODS = {"1d", "4h", "1h", "30m", "15m", "5m", "1m"}

# 默认最大执行时间：broker 拉 1m + 6 档 resample ≈ 60-180s
_SUBPROCESS_TIMEOUT = 240

# 进程级并发限流：1 个进程同时只跑 1 个分析（broker 限频）
import threading
_analysis_lock = threading.Lock()


# ============================================================
# Pydantic schemas
# ============================================================
class AnalysisRequest(BaseModel):
    stock_code: str = Field(..., min_length=4, max_length=20,
                            description="证券代码 e.g. 159992.SZ")
    periods: List[str] = Field(default_factory=lambda: ["1d"],
                               description="分析周期 1d/4h/1h/30m/15m/5m/1m")
    start_date: str = Field(..., pattern=r"^\d{8}$", description="YYYYMMDD")
    end_date: str = Field(..., pattern=r"^\d{8}$", description="YYYYMMDD")

    @root_validator(skip_on_failure=True)
    @classmethod
    def _validate_periods(cls, values):
        # values: dict in pydantic v1
        v = values.get("periods", [])
        bad = [p for p in v if p not in ALLOWED_PERIODS]
        if bad:
            raise ValueError(f"unsupported periods: {bad} (allowed: {sorted(ALLOWED_PERIODS)})")
        if not v:
            raise ValueError("periods must be non-empty")
        # 去重保序
        seen, out = set(), []
        for p in v:
            if p not in seen:
                seen.add(p)
                out.append(p)
        values["periods"] = out
        return values


class TableRow(BaseModel):
    """前端表格 1 行 = 1 个周期"""
    period: str
    score: Optional[float] = None
    trend: Optional[str] = None
    action: Optional[str] = None
    confidence: Optional[float] = None
    entry: Optional[float] = None
    stop: Optional[float] = None
    tp: Optional[float] = None
    rr: Optional[float] = None
    ema89: Optional[float] = None
    close: Optional[float] = None
    macd_hist: Optional[float] = None
    rsi: Optional[float] = None
    kdj_k: Optional[float] = None
    risk_source: Optional[str] = None
    error: Optional[str] = None


class AnalysisResponse(BaseModel):
    code: int = 0
    msg: str = ""
    report: Optional[dict] = None
    table_rows: List[TableRow] = Field(default_factory=list)
    synthesis: Optional[dict] = None
    elapsed_sec: float = 0.0
    disclaimer: str = (
        "本工具输出仅供研究/教育用途，不构成投资建议。"
        "投资有风险，决策需自负。"
    )


# ============================================================
# Demo 脚本调用 + stdout JSON 解析
# ============================================================
def _run_demo_script(req: AnalysisRequest) -> dict:
    """subprocess.run demo 脚本 + --json 模式，从 stdout 抓 JSON 块。"""
    if not os.path.isfile(_DEMO_SCRIPT):
        raise FileNotFoundError(
            f"demo script not found: {_DEMO_SCRIPT}. "
            "invest-analyst skill 未安装？"
        )

    periods_arg = ",".join(req.periods)
    cmd = [
        "python3",
        _DEMO_SCRIPT,
        "--stock",     req.stock_code,
        "--periods",   periods_arg,
        "--start",     req.start_date,
        "--end",       req.end_date,
        "--json",
        "--timeout",   "60",
    ]
    logger.info("[ai-analysis] cmd: %s", " ".join(cmd))

    # 进程级串行 — broker 限频保护
    with _analysis_lock:
        t0 = time.time()
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
            cwd=os.path.expanduser("~"),  # demo 脚本从 home 找 iquant
        )
        elapsed = time.time() - t0

    if proc.returncode != 0:
        stderr_tail = (proc.stderr or "")[-500:]
        logger.error("[ai-analysis] demo failed (rc=%s): %s", proc.returncode, stderr_tail)
        raise RuntimeError(
            f"demo script failed (rc={proc.returncode}): {stderr_tail}"
        )

    # demo 的 stdout 末尾有 `saved -> report_*.json` 这一行
    # 真实 JSON 是 demo 自己写盘的；这里我们重新跑读盘更稳
    json_path = _resolve_saved_json_path(req)
    if not json_path or not os.path.isfile(json_path):
        # 找最新的 report_<stock>_<periods>_<start>_<end>.json
        candidate = _find_latest_report(req)
        if not candidate:
            raise RuntimeError(
                "demo succeeded but report JSON not found on disk. "
                f"stdout tail: {(proc.stdout or '')[-300:]}"
            )
        json_path = candidate

    with open(json_path, "r", encoding="utf-8") as f:
        report = json.load(f)
    return {"report": report, "elapsed_sec": elapsed, "json_path": json_path}


def _resolve_saved_json_path(req: AnalysisRequest) -> Optional[str]:
    """demo 写盘的固定路径 = cwd + report_<stock>_<periods>_<start>_<end>.json"""
    periods_arg = "+".join(req.periods)
    name = f"report_{req.stock_code}_{periods_arg}_{req.start_date}_{req.end_date}.json"
    # demo 在 cwd 写盘 (hermes home)
    return os.path.join(os.path.expanduser("~"), name)


def _find_latest_report(req: AnalysisRequest) -> Optional[str]:
    """fallback: 找最近 5 分钟内匹配 stock_code 的 report JSON."""
    home = os.path.expanduser("~")
    prefix = f"report_{req.stock_code}_"
    try:
        cands = [
            os.path.join(home, f)
            for f in os.listdir(home)
            if f.startswith(prefix) and f.endswith(".json")
        ]
    except OSError:
        return None
    if not cands:
        return None
    # 按 mtime 倒序
    cands.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    # 5 分钟内
    fresh = [p for p in cands if (time.time() - os.path.getmtime(p)) < 300]
    return fresh[0] if fresh else None


# ============================================================
# 报告 → 表格 rows
# ============================================================
def _to_table_rows(report: dict) -> List[TableRow]:
    per = report.get("per_period", {})
    rows = []
    for tp, v in per.items():
        if "error" in v:
            rows.append(TableRow(period=tp, error=str(v["error"])))
            continue
        trend = v.get("trend", {})
        sub = trend.get("sub_scores", {})
        ind_raw = trend.get("indicators_raw", {}) or {}
        macd_raw = ind_raw.get("macd") or {}
        rsi_raw = ind_raw.get("rsi")
        kdj_raw = ind_raw.get("kdj") or {}
        ema89 = trend.get("ema89")
        try:
            close = v["summary"]["last_close"]
        except (KeyError, TypeError):
            close = None
        sig = (v.get("strategy_signals") or {}).get("latest_entry") or {}
        risk = v.get("risk") or {}
        rows.append(TableRow(
            period=tp,
            score=trend.get("score"),
            trend=trend.get("channel"),
            action=(v.get("advice") or {}).get("action"),
            confidence=(v.get("advice") or {}).get("confidence"),
            entry=risk.get("entry"),
            stop=risk.get("stop"),
            tp=risk.get("tp"),
            rr=risk.get("rr_ratio"),
            ema89=ema89,
            close=close,
            macd_hist=macd_raw.get("hist") if isinstance(macd_raw, dict) else None,
            rsi=rsi_raw if isinstance(rsi_raw, (int, float)) else None,
            kdj_k=kdj_raw.get("k") if isinstance(kdj_raw, dict) else None,
            risk_source=risk.get("source"),
        ))
    return rows


# ============================================================
# 端点
# ============================================================
@router.post("/ai-analysis", response_model=AnalysisResponse)
async def ai_analysis(req: AnalysisRequest):
    """同步 AI 分析 PoC。

    已知限制：
    - 进程级串行锁（broker 限频 / 账号白名单）
    - 超时 240s；超时客户端需 reload 再问
    - 不做缓存、不做异步、不做权限分级（演示账号即可）

    _run_demo_script 丢到 asyncio.to_thread (线程池) ——
    在 async def 里直接调 subprocess.run 会阻塞整个 event loop, 导致
    其他 UI 请求 (GET /api/positions 等) 在 ai_analysis 跑期间全部排队等待,
    表现"页面卡死/数据加载不出"。改用线程池后, 路由立刻返回 Future,
    FastAPI 在该线程内继续跑 subprocess.run, 不影响其他 async 路由。
    """
    logger.info(
        "[ai-analysis] request: stock=%s periods=%s %s~%s",
        req.stock_code, req.periods, req.start_date, req.end_date,
    )
    try:
        out = await asyncio.to_thread(_run_demo_script, req)
    except subprocess.TimeoutExpired:
        logger.warning("[ai-analysis] timeout after %ss", _SUBPROCESS_TIMEOUT)
        return AnalysisResponse(
            code=504,
            msg=f"分析超时（>{_SUBPROCESS_TIMEOUT}s），请缩小周期范围或日期区间后重试",
            elapsed_sec=_SUBPROCESS_TIMEOUT,
        )
    except FileNotFoundError as e:
        logger.error("[ai-analysis] %s", e)
        return AnalysisResponse(
            code=503,
            msg=f"invest-analyst skill 未安装：{e}",
        )
    except RuntimeError as e:
        logger.error("[ai-analysis] %s", e)
        return AnalysisResponse(code=500, msg=str(e))
    except Exception as e:
        logger.exception("[ai-analysis] unexpected error")
        return AnalysisResponse(code=500, msg=f"unexpected: {e}")

    report = out["report"]
    rows = _to_table_rows(report)
    syn = report.get("synthesis")
    return AnalysisResponse(
        code=0,
        msg="",
        report=report,
        table_rows=rows,
        synthesis=syn,
        elapsed_sec=round(out["elapsed_sec"], 1),
    )
