"""
server/strategy/runtime/__init__.py — 回测 + 实盘 runtime facade

暴露给 service 层 / API 层用的高层入口
"""
from server.strategy.runtime.sandbox import load_script, SandboxError
from server.strategy.runtime.grid import expand_params, MAX_COMBINATIONS
from server.strategy.runtime.backtest import BacktestEngine, BacktestResult, run_grid_backtest
from server.strategy.runtime.live import (
    LiveRunner,
    start_live_runner, stop_live_runner,
    is_running, get_running_ids,
    HQ_WS_URL,
)

__all__ = [
    # sandbox
    "load_script", "SandboxError",
    # grid
    "expand_params", "MAX_COMBINATIONS",
    # backtest
    "BacktestEngine", "BacktestResult", "run_grid_backtest",
    # live
    "LiveRunner",
    "start_live_runner", "stop_live_runner",
    "is_running", "get_running_ids", "HQ_WS_URL",
]