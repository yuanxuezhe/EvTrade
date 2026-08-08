"""
strategy_exec.main — FastAPI app 入口

启动:
    python -m strategy_exec.main --port 8001

或:
    python -m strategy_exec.main  # 默认 8001
"""

from __future__ import annotations

import argparse
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from strategy_exec import __version__
from strategy_exec.api.health import router as health_router
from strategy_exec.api.internal import router as internal_router
from strategy_exec.config import get_settings


def _setup_logging(level: str) -> None:
    """统一日志配置"""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan — 启动/关闭钩子

    Phase 1: 仅打 log
    Phase 2: 加 RabbitMQ connection pool, DB engine, LiveRunner manager
    """
    settings = get_settings()
    log = logging.getLogger(__name__)
    log.info(
        "[strategy_exec] v%s starting (port=%s, log_level=%s)",
        __version__, settings.strategy_exec_port, settings.log_level,
    )
    log.info("[strategy_exec] mysql=%s ...", settings.evtrade_db_url.split("@")[-1])
    log.info("[strategy_exec] rabbitmq=%s", settings.evtrade_rabbitmq_url)
    log.info("[strategy_exec] hq_ws=%s", settings.hq_ws_url)

    yield  # 应用运行中

    log.info("[strategy_exec] shutting down...")


def create_app() -> FastAPI:
    """FastAPI app factory"""
    app = FastAPI(
        title="StrategyExec",
        description="EvTrade 策略运行独立服务 (Backtrader + RabbitMQ)",
        version=__version__,
        lifespan=lifespan,
    )
    app.include_router(health_router)
    app.include_router(internal_router)
    return app


# 单例 app — uvicorn 直接用 `strategy_exec.main:app`
app = create_app()


def main() -> None:
    """CLI 入口: python -m strategy_exec.main"""
    parser = argparse.ArgumentParser(description="EvTrade strategy execution service")
    parser.add_argument("--host", default=None, help="监听 host (默认从 env STRATEGY_EXEC_HOST)")
    parser.add_argument("--port", type=int, default=None, help="监听端口 (默认从 env STRATEGY_EXEC_PORT)")
    parser.add_argument("--log-level", default=None, help="日志级别 (DEBUG/INFO/WARNING/ERROR)")
    parser.add_argument("--reload", action="store_true", help="开发模式自动重载")
    args = parser.parse_args()

    # 加载 settings (启动时校验, 缺 env 立即报错)
    settings = get_settings()
    _setup_logging(args.log_level or settings.log_level)

    import uvicorn
    uvicorn.run(
        "strategy_exec.main:app",
        host=args.host or settings.strategy_exec_host,
        port=args.port or settings.strategy_exec_port,
        reload=args.reload,
        log_level=(args.log_level or settings.log_level).lower(),
    )


if __name__ == "__main__":
    main()