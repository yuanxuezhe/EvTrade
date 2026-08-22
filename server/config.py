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

    # ---- strategy-exec-service (change strategy-exec-service) ----
    # signal 推送 exchange + queue (strategy_exec 推 signal → EvTrade 订阅)
    STRATEGY_EXCHANGE_NAME: str = _env("EVTRADE_STRATEGY_EXCHANGE_NAME", "strategy.exchange")
    STRATEGY_SIGNAL_QUEUE: str = _env("EVTRADE_STRATEGY_SIGNAL_QUEUE", "EvTrade.StrategySignal")
    # strategy_exec 服务 URL + token (forwarding endpoint 用)
    STRATEGY_EXEC_API_URL: str = _env("STRATEGY_EXEC_API_URL", "http://127.0.0.1:8001")
    STRATEGY_EXEC_API_TOKEN: str = _env("STRATEGY_EXEC_API_TOKEN", "")
    # service token (signal_consumer 调自家 /api/orders/place 用)
    EVTRADE_SERVICE_TOKEN: str = _env("EVTRADE_SERVICE_TOKEN", "")

    # ---- RPC 行为 ----
    RPC_TIMEOUT: float = _env_float("EVTRADE_RPC_TIMEOUT", 30.0)  # 单次 call 超时
    # 测试模式: 1=业务 RPC 调用不发真实请求, 直接返固定应答 (server/rpc/mock.py)
    # 启动时定死 (防运行中误切导致单子静默不发); 仅供无柜台/RabbitMQ 的开发/演示环境
    TEST_MODE: bool = _env_int("EVTRADE_TEST_MODE", 0) == 1

    # 下单时附带的 remark 备注（柜台透传字段，常用于区分下单来源）
    # 可通过 EVTRADE_ORDER_REMARK 环境变量覆盖
    ORDER_REMARK: str = _env("EVTRADE_ORDER_REMARK", "EvTrade.Test")

    # ---- FastAPI ----
    API_HOST: str = _env("EVTRADE_API_HOST", "0.0.0.0")
    API_PORT: int = _env_int("EVTRADE_API_PORT", 8001)

    # ---- 行情 (hqserver WS 地址, hq/hqserver.py 默认监听 8765) ----
    HQ_WS_URL: str = _env("HQ_WS_URL", "ws://127.0.0.1:8765")

    # ---- quote-batch-flush: quote_consumer 内合并参数 ----
    # 50 tick 或 1 秒强制 flush (股票级去重, 同窗口内同股票只推最新)
    QUOTE_BATCH_MAX = _env_int("QUOTE_BATCH_MAX", 50)
    QUOTE_BATCH_FLUSH_MS = _env_int("QUOTE_BATCH_FLUSH_MS", 1000)

    # ---- Historical K-line data (strategy_exec/market_data/hq_history.py) ----
    # 拉历史 K 线走独立 RabbitMQ 通道(同 broker, 不同 exchange/queue)
    # 请求队列必须是 EvTrade.ReqHisHq (broker 端 his_hq 应答服务消费此队列)
    # 此配置 EvTrade 已不直接用 (脚本策略迁移到 strategy_exec),
    # 但其他能力 (admin 拉历史 K 线验证等) 仍可用. 保留兼容
    HIS_HQ_RABBITMQ_URL: str = _env("EVTRADE_HIS_HQ_RABBITMQ_URL", "amqp://192.168.10.2:5672/")
    HIS_HQ_EXCHANGE_NAME: str = _env("EVTRADE_HIS_HQ_EXCHANGE_NAME", "quota_his.exchange")
    HIS_HQ_REQ_QUEUE: str = _env("EVTRADE_HIS_HQ_REQ_QUEUE", "EvTrade.ReqHisHq")
    HIS_HQ_TIMEOUT: float = _env_float("EVTRADE_HIS_HQ_TIMEOUT", 30.0)
    # broker 凭据 (默认 guest/guest, 生产应改)
    HIS_HQ_USER: str = _env("EVTRADE_HIS_HQ_USER", "guest")
    HIS_HQ_PASSWORD: str = _env("EVTRADE_HIS_HQ_PASSWORD", "guest")
    # broker 不响应时是否启用 demo 数据源 (用于本地体验完整回测流程)
    # 1=启用, 0=不启用 (broker 没数据直接 failed)
    HIS_HQ_FALLBACK_DEMO: bool = _env_int("EVTRADE_HIS_HQ_FALLBACK_DEMO", 0) == 1

    # ---- Quote cache ----
    # 内存 cache 周期性 flush 到 MySQL 的间隔（秒）。默认 60s，最小 5s。
    # 进程崩溃时最多丢失这段时间内的 snapshot。
    QUOTE_CACHE_FLUSH_INTERVAL: int = max(_env_int("QUOTE_CACHE_FLUSH_INTERVAL", 60), 5)
    # dirty 数量达到此阈值时也立即触发 flush（与定时器并列）
    QUOTE_CACHE_FLUSH_DIRTY_THRESHOLD: int = max(_env_int("QUOTE_CACHE_FLUSH_DIRTY_THRESHOLD", 100), 1)


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
