"""
strategy_exec.config — Pydantic Settings, 从 .env 读全部配置

设计原则:
- 所有 env 必须 STRATEGY_EXEC_*, EVTRADE_*, HQ_*, SANDBOX_* 4 个前缀之一
- 必填项缺时启动失败 (fail-fast)
- 与 EvTrade server/config.py 隔离 (独立服务, 不依赖)
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)

# 项目根 (strategy_exec/ 下)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """Pydantic Settings — 强类型 + 自动校验"""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.exists() else None,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ──── 服务端口 ────
    strategy_exec_port: int = Field(default=8001, ge=1, le=65535)
    strategy_exec_host: str = Field(default="0.0.0.0")
    strategy_exec_api_token: str = Field(min_length=16)  # 必填, 至少 16 字符

    # ──── MySQL（共享 EvTrade）────
    evtrade_db_url: str = Field(min_length=20)  # 必填
    evtrade_db_pool_size: int = Field(default=5, ge=1, le=50)
    evtrade_db_max_overflow: int = Field(default=10, ge=0, le=50)
    evtrade_db_pool_recycle: int = Field(default=1800, ge=60)
    evtrade_db_pool_pre_ping: bool = Field(default=True)

    # ──── RabbitMQ ────
    evtrade_rabbitmq_url: str = Field(min_length=10)
    evtrade_strategy_exchange_name: str = Field(default="strategy.exchange", min_length=1)
    evtrade_strategy_signal_queue: str = Field(default="EvTrade.StrategySignal", min_length=1)
    evtrade_strategy_publish_confirm_timeout: int = Field(default=5, ge=1, le=60)
    evtrade_strategy_publish_retries: int = Field(default=3, ge=0, le=10)
    evtrade_his_hq_exchange_name: str = Field(default="quota_his.exchange", min_length=1)
    evtrade_his_hq_req_queue: str = Field(default="EvTrade.ReqHisHq", min_length=1)
    evtrade_his_hq_req_timeout: int = Field(default=30, ge=5, le=300)

    # ──── 行情 WS ────
    hq_ws_url: str = Field(default="ws://127.0.0.1:8765/quota.broadcast", min_length=10)
    hq_ws_reconnect_base_delay: int = Field(default=1000, ge=100)
    hq_ws_reconnect_max_delay: int = Field(default=30000, ge=1000)
    hq_ws_heartbeat_interval: int = Field(default=30, ge=5)

    # ──── 沙箱 ────
    sandbox_blocked_modules: str = Field(
        default="os.system,subprocess,open,socket,requests,urllib,http.client",
    )
    sandbox_allowed_modules: str = Field(
        default="backtrader,numpy,pandas,math,json,datetime,typing",
    )

    # ──── 日志 ────
    log_level: str = Field(default="INFO")
    log_file: str = Field(default="")

    @field_validator("strategy_exec_api_token")
    @classmethod
    def _validate_token_not_default(cls, v: str) -> str:
        """防止开发者用占位 token 部署"""
        if v.startswith("__SET_"):
            raise ValueError(
                "STRATEGY_EXEC_API_TOKEN must be set (got placeholder). "
                "Generate with: openssl rand -hex 32"
            )
        return v

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, v: str) -> str:
        v = v.upper()
        if v not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            raise ValueError(f"invalid LOG_LEVEL: {v}")
        return v

    def blocked_module_list(self) -> List[str]:
        return [m.strip() for m in self.sandbox_blocked_modules.split(",") if m.strip()]

    def allowed_module_list(self) -> List[str]:
        return [m.strip() for m in self.sandbox_allowed_modules.split(",") if m.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """单例 — 启动时初始化一次, 后续复用"""
    try:
        return Settings()
    except Exception as e:
        log.error("config load failed: %s", e)
        raise SystemExit(f"config load failed: {e}")


def reload_settings() -> Settings:
    """测试用 — 清缓存重读"""
    get_settings.cache_clear()
    return get_settings()


__all__ = ["Settings", "get_settings", "reload_settings"]