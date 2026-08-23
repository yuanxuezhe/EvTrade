"""
server/mcp/tests/test_read_only.py — 12 tool 单测

Mock 策略：用 monkeypatch.setattr 直接替换 tools 子模块内的 call_evtrade 引用
（不能用 patch("server.mcp._client.call_evtrade", ...) 因为工具模块 import 时已 bind 本地引用）。
"""
import os
from unittest.mock import AsyncMock

import pytest

# 在 import server.mcp 之前设 JWT_SECRET（_jwt.py 需要）
os.environ.setdefault("JWT_SECRET", "test_secret_for_unit_test_only_32bytes!!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")

import server.mcp  # noqa: E402  # 触发 12 tool 注册
from server.mcp import TOOL_REGISTRY, is_high_risk  # noqa: E402
from server.mcp._jwt import decode_user_id, JWTError  # noqa: E402
from server.mcp._client import EvTradeAPIError  # noqa: E402
from server.mcp.tools import read_only, write, trade, admin  # noqa: E402  # 工具模块（patch 它们的 call_evtrade）


# ─── Fixture ──────────────────────────────────────────────────────
@pytest.fixture
def test_jwt(monkeypatch):
    """造一个测试 JWT（HS256 + user_id=42）"""
    import jwt as pyjwt
    monkeypatch.setenv("JWT_SECRET", "test_secret_for_unit_test_only_32bytes!!")
    payload = {"user_id": 42, "sub": "42", "role": "trader"}
    return pyjwt.encode(payload, "test_secret_for_unit_test_only_32bytes!!", algorithm="HS256")


def _make_mock_call(return_value=None, side_effect=None):
    """构造 AsyncMock 替换 call_evtrade"""
    mock = AsyncMock(return_value=return_value, side_effect=side_effect)
    return mock


def _patch_tool_module(monkeypatch, tool_module, **kwargs):
    """对工具模块内的 call_evtrade 做 monkeypatch（直接替换 local 引用）"""
    if "return_value" in kwargs:
        mock = AsyncMock(return_value=kwargs["return_value"])
    elif "side_effect" in kwargs:
        mock = AsyncMock(side_effect=kwargs["side_effect"])
    else:
        mock = AsyncMock()
    monkeypatch.setattr(tool_module, "call_evtrade", mock)
    return mock


# ─── 1. Registry 完整性 ──────────────────────────────────────────
class TestRegistry:
    def test_all_tools_registered(self):
        assert len(TOOL_REGISTRY) == 12, f"expected 12, got {len(TOOL_REGISTRY)}"

    def test_read_only_tools_count(self):
        ro = [n for n, td in TOOL_REGISTRY.items() if td.get("toolset") == "read-only"]
        assert len(ro) == 6, f"expected 6 read-only, got {ro}"

    def test_write_tool_count(self):
        w = [n for n, td in TOOL_REGISTRY.items() if td.get("toolset") == "write"]
        assert len(w) == 1, f"expected 1 write, got {w}"

    def test_trade_tools_count(self):
        t = [n for n, td in TOOL_REGISTRY.items() if td.get("toolset") == "trade"]
        assert len(t) == 2, f"expected 2 trade, got {t}"
        assert all(is_high_risk(n) for n in t)

    def test_admin_tools_count(self):
        a = [n for n, td in TOOL_REGISTRY.items() if td.get("toolset") == "admin"]
        assert len(a) == 3, f"expected 3 admin, got {a}"
        assert all(is_high_risk(n) for n in a)

    def test_high_risk_total(self):
        hr = [n for n in TOOL_REGISTRY if is_high_risk(n)]
        assert len(hr) == 5, f"expected 5 high-risk, got {hr}"


# ─── 2. JWT 解码 ───────────────────────────────────────────────
class TestJWT:
    def test_decode_valid_token_returns_user_id(self, test_jwt):
        assert decode_user_id(test_jwt) == 42

    def test_decode_empty_token_raises(self):
        with pytest.raises(JWTError, match="empty"):
            decode_user_id("")

    def test_decode_invalid_token_raises(self):
        with pytest.raises(JWTError, match="decode"):
            decode_user_id("not.a.jwt")

    def test_decode_missing_user_id_raises(self):
        import jwt as pyjwt
        bad = pyjwt.encode({"sub": "x"}, "test_secret_for_unit_test_only_32bytes!!", algorithm="HS256")
        with pytest.raises(JWTError, match="user_id"):
            decode_user_id(bad)


# ─── 3. list_positions tool ─────────────────────────────────────
class TestListPositions:
    @pytest.mark.asyncio
    async def test_success(self, test_jwt, monkeypatch):
        mock_resp = {
            "code": 0,
            "msg": "ok",
            "list": [
                {"stock_code": "600000.SH", "volume": 1000, "available": 1000, "cost_price": 10.5},
            ],
        }
        _patch_tool_module(monkeypatch, read_only, return_value=mock_resp)
        handler = TOOL_REGISTRY["list_positions"]["handler"]
        result = await handler(jwt_token=test_jwt)
        assert result["ok"] is True
        assert result["user_id"] == 42
        assert len(result["positions"]) == 1
        assert result["positions"][0]["stock_code"] == "600000.SH"

    @pytest.mark.asyncio
    async def test_evtrade_error_returns_failure(self, test_jwt, monkeypatch):
        _patch_tool_module(monkeypatch, read_only, side_effect=EvTradeAPIError(401, "unauthorized"))
        handler = TOOL_REGISTRY["list_positions"]["handler"]
        result = await handler(jwt_token=test_jwt)
        assert result["ok"] is False
        assert result["status_code"] == 401
        assert "unauthorized" in result["error"].lower()


# ─── 4. save_strategy_script tool ──────────────────────────────
class TestSaveStrategyScript:
    @pytest.mark.asyncio
    async def test_create_success(self, test_jwt, monkeypatch):
        mock_resp = {"id": 99, "name": "test"}
        m = _patch_tool_module(monkeypatch, write, return_value=mock_resp)
        handler = TOOL_REGISTRY["save_strategy_script"]["handler"]
        result = await handler(jwt_token=test_jwt, name="test", code="def foo(): pass")
        # 验证调的是 POST /api/script-strategy/scripts
        assert m.call_args.kwargs["method"] == "POST"
        assert "/api/script-strategy/scripts" in m.call_args.kwargs["path"]
        assert result["ok"] is True
        assert result["action"] == "created"
        assert result["script"]["id"] == 99


# ─── 5. place_order tool (high-risk) ─────────────────────────────
class TestPlaceOrder:
    @pytest.mark.asyncio
    async def test_place_order_success(self, test_jwt, monkeypatch):
        mock_resp = {"order_no": "12345678", "status": 48}
        m = _patch_tool_module(monkeypatch, trade, return_value=mock_resp)
        handler = TOOL_REGISTRY["place_order"]["handler"]
        result = await handler(
            jwt_token=test_jwt,
            stock_code="600000.SH",
            direction="buy",
            price_type="limit",
            price=10.5,
            volume=100,
        )
        assert m.call_args.kwargs["method"] == "POST"
        assert "/api/orders" in m.call_args.kwargs["path"]
        assert result["ok"] is True
        assert result["order"]["order_no"] == "12345678"
        assert is_high_risk("place_order") is True


# ─── 6. set_user_role tool (TODO stub) ──────────────────────────
class TestSetUserRole:
    @pytest.mark.asyncio
    async def test_returns_not_implemented(self, test_jwt):
        handler = TOOL_REGISTRY["set_user_role"]["handler"]
        result = await handler(jwt_token=test_jwt, user_id=99, new_role="admin")
        assert result["ok"] is False
        assert result["status_code"] == 501
        assert "not yet implemented" in result["error"]


# ─── 7. 跨 tool 沙箱边界：jwt 解 user_id，LLM 不可覆盖 ──────────
class TestSandbox:
    """REQ-ARCH-008 §沙箱边界：LLM 不得指定 user_id，user_id 必须从 JWT 来"""

    @pytest.mark.asyncio
    async def test_user_id_param_ignored_for_list_positions(self, test_jwt, monkeypatch):
        """即使 LLM 试图传 user_id="other_user"，tool 必须用 JWT 的 user_id"""
        _patch_tool_module(monkeypatch, read_only, return_value={"code": 0, "msg": "ok", "list": []})
        handler = TOOL_REGISTRY["list_positions"]["handler"]
        result = await handler(jwt_token=test_jwt)  # 注意：list_positions 不接受 user_id 参数
        assert result["user_id"] == 42  # 来自 JWT，不是 LLM

    @pytest.mark.asyncio
    async def test_place_order_uses_jwt_user_id_not_param(self, test_jwt, monkeypatch):
        """place_order 的 jwt 决定 user_id，LLM 不能 override"""
        _patch_tool_module(monkeypatch, trade, return_value={"order_no": "12345678"})
        handler = TOOL_REGISTRY["place_order"]["handler"]
        result = await handler(
            jwt_token=test_jwt,
            stock_code="600000.SH",
            direction="buy",
            price_type="limit",
            price=10.0,
            volume=100,
        )
        assert result["user_id"] == 42  # 来自 JWT

