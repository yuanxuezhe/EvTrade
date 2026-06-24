"""
lifecycle/__init__.py — 启动 / 关闭 hook
"""
from server.lifecycle.seed import init_and_seed

__all__ = ["init_and_seed"]
