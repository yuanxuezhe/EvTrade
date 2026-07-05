"""
Centralized configuration for EvTrade backend.

All tunables live here. Values can be overridden via environment variables
(loaded from a `.env` file in the server directory if present).

Usage:
    from config import settings
    print(settings.RABBITMQ_URL)
"""
import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
    _ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(_ENV_PATH):
        load_dotenv(_ENV_PATH, override=False)
except ImportError:  # python-dotenv optional
    pass


def _env(key: str, default: str) -> str:
    v = os.environ.get(key)
    return v if v not in (None, "") else default


def _env_int(key: str, default: int) -> int:
    try:
        return int(_env(key, str(default)))
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(_env(key, str(default)))
    except ValueError:
        return default


def _secret_path() -> str:
    """JWT 密钥文件路径"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), ".secret_key")


class ConfigValidator:
    """配置验证器：启动时集中检查关键配置"""
    errors: list
    warnings: list

    def __init__(self):
        self.errors = []
        self.warnings = []

    def validate(self) -> bool:
        """执行所有验证，返回是否通过"""
        # 1. JWT_SECRET 检查
        if not os.environ.get("EVTRADE_SECRET") and not os.path.exists(_secret_path()):
            # 首次启动会自动生成，仅警告
            self.warnings.append("EVTRADE_SECRET 未设置，首次启动将自动生成")

        # 2. RabbitMQ URL 必须配置
        if not settings.RABBITMQ_URL:
            self.errors.append("RABBITMQ_URL 未配置")

        # 3. RPC 超时合理性
        if settings.RPC_TIMEOUT <= 0 or settings.RPC_TIMEOUT > 300:
            self.warnings.append(f"RPC_TIMEOUT={settings.RPC_TIMEOUT}s 异常（建议 5-120s）")

        # 4. 端口范围
        if settings.API_PORT < 1 or settings.API_PORT > 65535:
            self.errors.append(f"INVALID_API_PORT: {settings.API_PORT}")

        return len(self.errors) == 0


@dataclass(frozen=True)
class Settings:
    # ---- RabbitMQ ----
    RABBITMQ_URL: str = _env("EVTRADE_RABBITMQ_URL", "amqp://192.168.10.2:5672/")

    # 交易所用的 topic exchange（柜台/EvTrade 共同约定）
    EXCHANGE_NAME: str = _env("EVTRADE_EXCHANGE_NAME", "msgpacket.exchange")

    # 三条 durable 队列：请求 / 应答 / 推送
    QUEUE_REQ: str   = _env("EVTRADE_QUEUE_REQ",   "EvTrade.Test.Req")
    QUEUE_REPLY: str = _env("EVTRADE_QUEUE_REPLY", "EvTrade.Test.Reply")
    QUEUE_PUSH: str  = _env("EVTRADE_QUEUE_PUSH",  "EvTrade.Test.Push")

    # ---- RPC 行为 ----
    RPC_TIMEOUT: float = _env_float("EVTRADE_RPC_TIMEOUT", 30.0)  # 单次 call 超时

    # 下单时附带的 remark 备注（柜台透传字段，常用于区分下单来源）
    # 可通过 EVTRADE_ORDER_REMARK 环境变量覆盖
    ORDER_REMARK: str = _env("EVTRADE_ORDER_REMARK", "EvTrade.Test")

    # ---- FastAPI ----
    API_HOST: str = _env("EVTRADE_API_HOST", "0.0.0.0")
    API_PORT: int = _env_int("EVTRADE_API_PORT", 8001)

    # ---- Strategy engine (change strategy_trade task 7) ----
    # 灰度开关：false 时 quote_consumer 不启动，strategy REST API 返 503
    STRATEGY_ENGINE_ENABLED: bool = _env_int("STRATEGY_ENGINE_ENABLED", 0) == 1
    # hqserver WS 地址（hq/hqserver.py 默认监听 8765）
    HQ_WS_URL: str = _env("HQ_WS_URL", "ws://127.0.0.1:8765")


settings = Settings()


def validate_config():
    """验证配置并打印警告/错误"""
    validator = ConfigValidator()
    passed = validator.validate()

    if validator.warnings:
        print("[CONFIG] Warnings:")
        for w in validator.warnings:
            print(f"  [WARN] {w}")

    if not passed:
        print("[CONFIG] Errors:")
        for e in validator.errors:
            print(f"  [ERROR] {e}")
        raise RuntimeError(f"Config validation failed: {validator.errors}")

    print("[CONFIG] All validations passed")
