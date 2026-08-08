"""strategy_exec.templates — 默认模板包 (Phase 5)

提供 Backtrader 默认用户脚本代码 + params_schema

📌 延迟加载 backtrader: 顶层 import backtrader 会导致无 backtrader 环境 (e.g. 迁移脚本) 无法导入本模块
   所以 DEFAULT_BT_STRATEGY_CODE 是字符串常量 (不执行), 无需 backtrader
   但 default_bt_strategy.py 顶层 `import backtrader as bt` 仅用于类型注解 — 用 try/except 兜底
"""

from __future__ import annotations

from strategy_exec.templates.default_bt_strategy import (
    DEFAULT_BT_STRATEGY_CODE,
    DEFAULT_BT_STRATEGY_PARAMS_SCHEMA,
)

__all__ = ["DEFAULT_BT_STRATEGY_CODE", "DEFAULT_BT_STRATEGY_PARAMS_SCHEMA"]