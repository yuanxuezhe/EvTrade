"""
server/rpc/mock.py — 测试模式 RPC 固定应答

`EVTRADE_TEST_MODE=1` 时, 业务 RPC 调用 (handlers.py 的 qry_*/ord_stk/cancel_order)
**不发真实请求**, 由本模块直接返回固定应答 dict `{code, msg, list}`。

设计:
- `maybe_reply(func, **kw) -> dict | None`: 测试模式关闭 → None (走真实链路);
  开启 → 返回对应 func 的固定应答。
- 查询类: `qry_ast` 固定资产 demo; `qry_ord/qry_mch/qry_pos` 空集 (不污染 DB)。
- `ord_stk`: 动态 `order_id` (`TEST-<seq>` 进程内递增), 让调用方拿到真实格式的应答。
- `cxl_ord`: 成功空集。

限制: 只 mock RPC **请求应答**, 不模拟 broker 异步 push (ord_cfm/trd_cfm)。
因此测试模式下下单会停在 status=48 (真实流程靠 ord_cfm push 推进到 50)。
"""
from typing import Any, Dict, Optional

from server.config import settings

# ord_stk mock order_id 计数器 (进程内递增, 重启归零; orders 无唯一约束, 不冲突)
_ord_seq: int = 0


def _next_order_id() -> str:
    global _ord_seq
    _ord_seq += 1
    return f"TEST-{_ord_seq:05d}"


def _asset_reply() -> Dict[str, Any]:
    return {
        "code": 0,
        "msg": "",
        "list": [{
            "account_id": "TEST",
            "cash": 1000000.0,
            "frozen_cash": 0.0,
            "market_value": 50000.0,
            "total_asset": 1050000.0,
        }],
    }


def _empty_reply() -> Dict[str, Any]:
    return {"code": 0, "msg": "", "list": []}


def _ord_stk_reply(**kw) -> Dict[str, Any]:
    return {
        "code": 0,
        "msg": "",
        "list": [{"order_id": _next_order_id(), "order_status": "50"}],
    }


# func(handler 调用的渠道名) → 应答构造器
_MOCK_BUILDERS: Dict[str, Any] = {
    "qry_ast": _asset_reply,      # 查询资金
    "qry_ord": _empty_reply,      # 查询委托
    "qry_mch": _empty_reply,      # 查询成交
    "qry_pos": _empty_reply,      # 查询持仓
    "ord_stk": _ord_stk_reply,    # 下单
    "cxl_ord": _empty_reply,      # 撤单
}


def maybe_reply(func: str, **kw) -> Optional[Dict[str, Any]]:
    """测试模式下返回 func 的固定应答 dict; 否则 None (走真实 RPC).

    Args:
        func: 柜台渠道名 (qry_ast / qry_ord / qry_mch / qry_pos / ord_stk / cxl_ord)
        **kw: 调用参数 (mock 固定应答暂不依赖, 透传供将来按需定制)
    """
    if not settings.TEST_MODE:
        return None
    builder = _MOCK_BUILDERS.get(func)
    if builder is None:
        # 未登记的渠道: 保守返回空成功, 避免测试模式下未 mock 的调用打到真实柜台
        return _empty_reply()
    return builder(**kw)
