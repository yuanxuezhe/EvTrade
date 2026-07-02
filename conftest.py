"""
conftest.py — pytest 全局配置 + 修复 Base 重复注册问题

问题背景：
  server/test_*.py 大量用 `sys.path.insert(0, 'server/')` 后直接
  `from db import Base` / `from models.orm import Order` 触发裸名 import。
  但生产代码 `server/models/orm.py` 内部 `from server.db import Base`
  走的是 `server.*` 限定名。两路 import 命中 orm.py 两次（裸名 vs
  限定名是两个 sys.modules entry），`class Order(Base)` 被声明两次，
  撞 SQLAlchemy `Table 'orders' is already defined for this MetaData instance`。

解决：
  1. 把项目根加 sys.path，让 `server.*` 包可被 import。
  2. 预加载 `server.*` 模块到 sys.modules（带限定名）。
  3. 把同一模块实例以裸名（`db` / `models.orm` / ...）也注册到
     sys.modules，强制 test 文件的裸名 import 命中同一模块对象。

这样无论 test 用哪种 import 风格，orm.py 只被加载一次，
SQLAlchemy 声明基类只注册一次。

注意：
  - 本文件不动 test 文件本身（保持向后兼容）。
  - 也不动生产代码（生产代码用 `from server.X` 走限定名）。
  - 跑测试时仍 `cd D:/workspace/EvTrade && python -m pytest server/ -v`。
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

# AsyncMock shim for Python 3.6 (stdlib AsyncMock only exists in 3.8+)
try:
    from unittest.mock import AsyncMock as _stdlib_AsyncMock  # noqa: F401
    AsyncMock = _stdlib_AsyncMock
except ImportError:
    import unittest.mock as _um

    class AsyncMock(MagicMock):
        """Minimal AsyncMock backport: awaitable + tracks await_args / await_count / await_args_list.

        Usage: AsyncMock(return_value={...}) — same API as 3.8+ stdlib.
        """
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._await_calls = []  # list of (args, kwargs) tuples

        async def __call__(self, *args, **kwargs):
            self._await_calls.append((args, kwargs))
            return super().__call__(*args, **kwargs)

        @property
        def await_count(self):
            return len(self._await_calls)

        @property
        def await_args(self):
            if not self._await_calls:
                return None
            args, kwargs = self._await_calls[-1]
            return self._make_await_args(args, kwargs)

        @property
        def await_args_list(self):
            return [self._make_await_args(a, kw) for a, kw in self._await_calls]

        @staticmethod
        def _make_await_args(args, kwargs):
            class _AwaitArgs:
                def __init__(self, args, kwargs):
                    self.args = args
                    self.kwargs = kwargs
            return _AwaitArgs(args, kwargs)

    # Inject into unittest.mock so test files can do
    # `from unittest.mock import AsyncMock` (3.8+ idiom).
    _um.AsyncMock = AsyncMock

# 1. 项目根入 sys.path，让 `server.*` 可 import
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 2. 预加载 server.* 包内模块
import server.db as _server_db
import server.models.orm as _server_orm
import server.models.user as _server_user
import server.services.order_no as _server_order_no
import server.services.order_status as _server_order_status
import server.services.guards as _server_guards
import server.services.reconcile as _server_reconcile
import server.services.t0 as _server_t0
import server.services.push.handlers as _server_push_handlers
import server.services.push.ord as _server_push_ord
import server.services.push.trd as _server_push_trd
import server.services.push.pos as _server_push_pos
import server.services.push.ast as _server_push_ast
import server.services.push.helpers as _server_push_helpers
import server.services.trading_clock as _server_trading_clock
import server.auth.security as _server_auth_security
import server.auth.deps as _server_auth_deps
import server.enums.trading as _server_enums_trading
import server.utils.time as _server_utils_time
import server.rpc.client as _server_rpc_client
import server.ws.manager as _server_ws_manager
import server.main as _server_main

# Pre-load api.* modules so monkeypatch.setattr('api.X', ...) can resolve them
import server.api as _server_api
import server.api.orders as _server_api_orders
import server.api.orders.place as _server_api_orders_place
import server.api.orders.cancel as _server_api_orders_cancel
import server.api.orders.query as _server_api_orders_query
import server.api.holdings as _server_api_holdings
import server.api.system as _server_api_system
import server.api.trades as _server_api_trades
import server.api.t0_aggregate as _server_api_t0_aggregate
import server.api.users as _server_api_users
import server.api.auth as _server_api_auth

# 3. 裸名别名：test 文件 sys.path.insert(0, 'server/') 后
#    `from db import X` 走裸名，强制命中同一模块对象
_BARE_ALIASES = {
    "db": _server_db,
    "models": sys.modules.get("server.models"),  # 由 _server_orm 加载时已存在
    "models.orm": _server_orm,
    "models.user": _server_user,
    "services": sys.modules.get("server.services"),
    "services.order_no": _server_order_no,
    "services.order_status": _server_order_status,
    "services.guards": _server_guards,
    "services.reconcile": _server_reconcile,
    "services.t0": _server_t0,
    "services.trading_clock": _server_trading_clock,
    "services.push": sys.modules.get("server.services.push"),
    "services.push.handlers": _server_push_handlers,
    "services.push.ord": _server_push_ord,
    "services.push.trd": _server_push_trd,
    "services.push.pos": _server_push_pos,
    "services.push.ast": _server_push_ast,
    "services.push.helpers": _server_push_helpers,
    "auth": sys.modules.get("server.auth"),
    "auth.security": _server_auth_security,
    "auth.deps": _server_auth_deps,
    "enums": sys.modules.get("server.enums"),
    "enums.trading": _server_enums_trading,
    "utils": sys.modules.get("server.utils"),
    "utils.time": _server_utils_time,
    "rpc": sys.modules.get("server.rpc"),
    "rpc.client": _server_rpc_client,
    "ws": sys.modules.get("server.ws"),
    "ws.manager": _server_ws_manager,
    "main": _server_main,
    "api": sys.modules.get("server.api"),
    "api.orders": _server_api_orders,
    "api.orders.place": _server_api_orders_place,
    "api.orders.cancel": _server_api_orders_cancel,
    "api.orders.query": _server_api_orders_query,
    "api.holdings": _server_api_holdings,
    "api.system": _server_api_system,
    "api.trades": _server_api_trades,
    "api.t0_aggregate": _server_api_t0_aggregate,
    "api.users": _server_api_users,
    "api.auth": _server_api_auth,
}
for _name, _mod in _BARE_ALIASES.items():
    if _mod is not None:
        sys.modules[_name] = _mod
