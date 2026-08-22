"""
test_rpc_mock.py — RPC 测试模式固定应答 (sys_config rpc_test_mode)

覆盖 server/rpc/mock.py + handlers.py 短路:
- rpc_test_mode=0 → maybe_reply 返回 None (走真实链路)
- rpc_test_mode=1 → 各 handler 返回固定应答, 且不调 get_rpc_client (不发请求)
- ord_stk mock order_id 进程内递增
- 开关切换即时生效 (每次调用读 sysconfig 缓存)

测试用 monkeypatch 替换 sysconfig.get, 不碰 DB.
"""
import pytest

from server.services import sysconfig
from server.rpc.mock import maybe_reply, CONFIG_KEY
from server.rpc import handlers


@pytest.fixture
def test_mode(monkeypatch):
    """模拟 rpc_test_mode=1 (不写 DB, 只替换 sysconfig.get)"""
    def fake_get(key, default=None, user="0"):
        return 1 if key == CONFIG_KEY else default
    monkeypatch.setattr(sysconfig, "get", fake_get)
    yield


def test_maybe_reply_off_returns_none(monkeypatch):
    """rpc_test_mode=0 → maybe_reply 返回 None, 不短路"""
    def fake_get(key, default=None, user="0"):
        return default
    monkeypatch.setattr(sysconfig, "get", fake_get)
    assert maybe_reply("qry_ast") is None
    assert maybe_reply("ord_stk") is None


def test_toggle_takes_effect_immediately(monkeypatch):
    """同进程内切开关即时生效 (每次调用读缓存)"""
    state = {"on": False}

    def fake_get(key, default=None, user="0"):
        return 1 if (key == CONFIG_KEY and state["on"]) else default
    monkeypatch.setattr(sysconfig, "get", fake_get)

    assert maybe_reply("qry_ast") is None
    state["on"] = True
    assert maybe_reply("qry_ast")["code"] == 0
    state["on"] = False
    assert maybe_reply("qry_ast") is None


def test_qry_asset_fixed_demo(test_mode):
    """测试模式 qry_ast → 固定资产 demo"""
    r = maybe_reply("qry_ast")
    assert r["code"] == 0
    assert len(r["list"]) == 1
    a = r["list"][0]
    assert a["cash"] == 1000000.0
    assert a["total_asset"] == 1050000.0


def test_query_empty_sets(test_mode):
    """测试模式 qry_ord/qry_mch → 空集 (委托/成交靠 push, 不 mock)"""
    for func in ("qry_ord", "qry_mch"):
        r = maybe_reply(func)
        assert r["code"] == 0
        assert r["list"] == [], f"{func} 应为空集"


def test_qry_pos_demo_159992(test_mode):
    """测试模式 qry_pos → demo 159992.SZ 持仓"""
    r = maybe_reply("qry_pos")
    assert r["code"] == 0
    assert len(r["list"]) == 1
    p = r["list"][0]
    assert p["stock_code"] == "159992.SZ"
    assert p["vol"] == 10000
    assert p["avl_vol"] == 10000
    assert p["cost_price"] == 1.50


def test_ord_stk_order_id_increments(test_mode):
    """ord_stk mock order_id 每次调用递增 (TEST-00001 → TEST-00002)"""
    r1 = maybe_reply("ord_stk")
    r2 = maybe_reply("ord_stk")
    id1 = r1["list"][0]["order_id"]
    id2 = r2["list"][0]["order_id"]
    assert id1.startswith("TEST-")
    assert id2.startswith("TEST-")
    assert id1 != id2


def test_cxl_ord_success(test_mode):
    """cxl_ord → 成功空集"""
    r = maybe_reply("cxl_ord")
    assert r["code"] == 0
    assert r["list"] == []


@pytest.mark.asyncio
async def test_handlers_short_circuit_without_connect(test_mode, monkeypatch):
    """测试模式 handler 直接返 mock, 不调 get_rpc_client (不发真实请求)"""
    calls = []

    async def _raise_if_called():
        calls.append(1)
        raise AssertionError("测试模式不应调用 get_rpc_client")

    monkeypatch.setattr(handlers, "get_rpc_client", _raise_if_called)

    a = await handlers.qry_asset()
    o = await handlers.ord_stk(
        stock_code="600519.SH", volume=100, price_type=0, price=1800.0, order_type="23",
    )
    c = await handlers.cancel_order(order_id="TEST-00001")

    assert a["code"] == 0
    assert o["list"][0]["order_id"].startswith("TEST-")
    assert c["code"] == 0
    assert calls == [], "测试模式 handlers 不应触碰 RPC 连接"
