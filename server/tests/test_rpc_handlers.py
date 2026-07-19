"""
test_rpc_handlers.py — RPC handlers 撤单契约测试 (REQ-TRADE-033)

覆盖:
  1. cancel_order 调用渠道名为 cxl_ord (不是 cancel_ord)
  2. cancel_order values 仅含 order_id, 不含 market
  3. cancel_order headers = "order_id" (单 value)
  4. cancel_order 函数签名无 market 参数

不连接真 broker, 仅 mock get_rpc_client 验证 call 参数.
_parse_order_ack 需要真实 MsgPacket (C 扩展), 此测试不覆盖其内部逻辑.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from server.rpc.handlers import cancel_order


@pytest.fixture
def fake_rpc_client():
    """mock RPClient.call, 返回值不重要 (此测试只验证 call 调用参数)"""
    client = MagicMock()
    # side_effect 抛错也 OK, 我们只看 call_args
    client.call = AsyncMock(side_effect=RuntimeError("test stopped here"))
    return client


async def test_cancel_order_uses_cxl_ord_channel(fake_rpc_client):
    """REQ-TRADE-033: 柜台真实渠道名 = cxl_ord, 不是 cancel_ord"""
    with patch("server.rpc.handlers.get_rpc_client", AsyncMock(return_value=fake_rpc_client)):
        with pytest.raises(RuntimeError):
            await cancel_order(order_id="ORD123")
        fake_rpc_client.call.assert_called_once()
        channel = fake_rpc_client.call.call_args[0][0]
        assert channel == "cxl_ord", f"期望渠道 cxl_ord, 实际 {channel!r}"


async def test_cancel_order_values_only_order_id(fake_rpc_client):
    """REQ-TRADE-033: values 仅 order_id, 不带 market (用户确认去掉 market 参数)"""
    with patch("server.rpc.handlers.get_rpc_client", AsyncMock(return_value=fake_rpc_client)):
        with pytest.raises(RuntimeError):
            await cancel_order(order_id="ORD123")
        _, kwargs = fake_rpc_client.call.call_args
        assert "values" in kwargs
        assert kwargs["values"] == {"order_id": "ORD123"}, (
            f"期望 values={{'order_id': 'ORD123'}}, 实际 {kwargs['values']!r}"
        )
        # 守门: 不能有 market 字段
        assert "market" not in kwargs["values"]


async def test_cancel_order_headers_single_order_id(fake_rpc_client):
    """REQ-TRADE-033: headers = 'order_id' (单 value), 不是 'market|order_id'"""
    with patch("server.rpc.handlers.get_rpc_client", AsyncMock(return_value=fake_rpc_client)):
        with pytest.raises(RuntimeError):
            await cancel_order(order_id="ORD123")
        _, kwargs = fake_rpc_client.call.call_args
        assert kwargs.get("headers") == "order_id", (
            f"期望 headers='order_id', 实际 {kwargs.get('headers')!r}"
        )


def test_cancel_order_signature_has_no_market():
    """REQ-TRADE-033: cancel_order 函数签名无 market 参数"""
    import inspect
    sig = inspect.signature(cancel_order)
    params = list(sig.parameters.keys())
    assert "order_id" in params
    assert "market" not in params, (
        f"签名不应有 market, 实际参数: {params}"
    )