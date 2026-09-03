"""
server.services.quote_sync.broker — broker 客户端 thin wrapper

📌 change 2026-09-03 unify-his-hq-broker-client:
- 历史行情下载/解析逻辑统一到 strategy_exec.market_data.his_hq_client
  (跨 server + scripts + strategy_exec 三处共用)
- 本文件只保留 server 端的薄壳:
  - 单例 (get_his_hq_client / close_his_hq_client)
  - HisHqClient 继承, settings override (server 用 settings.HIS_HQ_* 而非
    strategy_exec settings.evtrade_*)
  - to_record 跟 END_OF_HIS_HQ_MARKER 转发 (从公共模块导入, 不重复定义)

历史:
- d40d9c1 feat(quote-sync): broker 自包含 + VWAP
- 9b81088 feat(quote-sync): 周末本地跳过 (方案A, 后续改 B方案)
- 2026-09-03 字段兜底 (broker 实盘只返 close, OHL 用 close 兜底)
- 2026-09-03 unify-his-hq-broker-client (本 change)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from strategy_exec.market_data.his_hq_client import (
    END_OF_HIS_HQ_MARKER,  # noqa: F401  转发导出, 兼容外部 import
    HisHqClient as _HisHqClient,
    to_record,
)

from server.config import settings

log = logging.getLogger(__name__)


# 协议字段 (xtquant get_market_data_ex 支持的字段) — 复用公共默认
BROKER_FIELDS = ["open", "high", "low", "close", "volume", "amount"]


class BrokerError(Exception):
    """拉 broker 历史行情失败 (区分于「空日」— 空日不 raise)"""


class HisHqClient(_HisHqClient):
    """server 端 HisHqClient — 覆盖 settings provider 用 server config.

    父类 _HisHqClient 默认读 strategy_exec 的 pydantic settings
    (evtrade_rabbitmq_url / evtrade_his_hq_exchange_name / evtrade_his_hq_req_queue).
    server 用自己的 settings.HIS_HQ_*. 这里 override settings property 把 server
    settings 注入.
    """

    @property
    def settings(self) -> Any:  # type: ignore[override]
        """server 用 BaseSettings (非 pydantic)."""
        return settings

    def _resolve(self, key: str) -> Any:  # type: ignore[override]
        """先看 override, 再看 server settings.HIS_HQ_*."""
        v = self._overrides.get(key)
        if v is not None:
            return v
        if key == "rabbitmq_url":
            return settings.HIS_HQ_RABBITMQ_URL
        if key == "exchange_name":
            return settings.HIS_HQ_EXCHANGE_NAME
        if key == "req_queue":
            return settings.HIS_HQ_REQ_QUEUE
        if key == "timeout":
            return settings.HIS_HQ_TIMEOUT
        return None


# ───────────────────────── 单例 helpers (server 端) ─────────────────────────

_client: Optional[HisHqClient] = None


def get_his_hq_client() -> HisHqClient:
    """返单例 (lazy init). 调用方负责 await connect() 和 close()."""
    global _client
    if _client is None:
        _client = HisHqClient()
    return _client


async def close_his_hq_client() -> None:
    """应用关闭时调用."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None


# ───────────────────────── 转发导出 (兼容旧 server 端 import) ─────────────────────────
# - tests/services/quote_sync/test_broker.py 仍 from server.services.quote_sync.broker import
#   to_record, _weekdays_in, _iter_rows — 全部从公共模块转发, 行为不变
from strategy_exec.market_data.his_hq_client import (  # noqa: E402,F401
    _iter_rows,
    _to_float,
    _weekdays_in,
)


__all__ = [
    "BROKER_FIELDS",
    "BrokerError",
    "HisHqClient",
    "to_record",
    "_iter_rows",
    "_to_float",
    "_weekdays_in",
    "END_OF_HIS_HQ_MARKER",
    "get_his_hq_client",
    "close_his_hq_client",
]