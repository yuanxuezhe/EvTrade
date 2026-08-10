"""strategy_exec 单测 conftest — 让 `import strategy_exec` 命中内层包.

仓库外层 `strategy_exec/` 无 __init__.py (namespace 包), 若仅把 repo 根入
sys.path, `strategy_exec.engines` 无法解析。此处把内层包目录
`<repo>/strategy_exec/` 置顶, 使 `strategy_exec` 解析为真正包。
"""
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PKG_DIR = os.path.join(_REPO_ROOT, "strategy_exec")
if _PKG_DIR not in sys.path:
    sys.path.insert(0, _PKG_DIR)
