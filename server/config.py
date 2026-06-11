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


settings = Settings()
