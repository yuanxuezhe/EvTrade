"""
server/mcp/__init__.py — evtrade-mcp package entry

通过 import 副作用注册全部 12 个 tool 到 TOOL_REGISTRY。
FastAPI agent.py 一句 `import server.mcp` 即可。
"""
# 触发 tool 注册副作用（每个 tools/*.py 顶层调用 register()）
from .tools import read_only  # noqa: F401  # 6 read-only tools
from .tools import write  # noqa: F401  # 1 low-risk write tool
from .tools import trade  # noqa: F401  # 2 high-risk trade tools
from .tools import admin  # noqa: F401  # 3 high-risk admin tools

from ._registry import TOOL_REGISTRY, list_tools, is_high_risk, get_handler  # noqa: F401

__all__ = ["TOOL_REGISTRY", "list_tools", "is_high_risk", "get_handler"]
