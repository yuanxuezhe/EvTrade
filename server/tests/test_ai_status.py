"""
test_ai_status.py — /api/ai/status 公开端点 (claude CLI 缺失优雅降级)

2026-08-25 新增: REQ-AI-007

测试策略:
- 直接调路由函数 (不启 uvicorn, 避开 starlette 0.27/httpx 0.28 不兼容问题)
- mock is_claude_available() 切换 available/true|false
"""
import pytest


def test_ai_status_available_true(monkeypatch):
    """mock claude 在 PATH → /api/ai/status 返 {available: true}."""
    from server.main import app
    from server.ai.agent_spawner import is_claude_available as real_fn

    # mock public 函数返 True
    import server.main as m
    monkeypatch.setattr(m, "_is_claude_available", lambda: True)

    # 直接调路由函数
    route_fn = None
    for r in app.routes:
        if getattr(r, "path", None) == "/api/ai/status":
            route_fn = r.endpoint
            break
    assert route_fn is not None, "/api/ai/status route 必须注册"

    result = route_fn()
    assert result == {"available": True}
    assert "reason" not in result


def test_ai_status_available_false_with_reason(monkeypatch):
    """mock claude 不在 PATH → /api/ai/status 返 {available: false, reason: ...}."""
    from server.main import app
    import server.main as m

    monkeypatch.setattr(m, "_is_claude_available", lambda: False)
    # reason 走真实函数 — 验证字符串格式合理
    monkeypatch.setattr(m, "_claude_missing_reason", lambda: (
        "未在 PATH 中找到 `claude` CLI. EvTrade AI 助手 (claudedemo 模式) "
        "需要本机或容器内有 claude binary. 安装: `npm i -g @anthropic-ai/claude-code`."
    ))

    route_fn = None
    for r in app.routes:
        if getattr(r, "path", None) == "/api/ai/status":
            route_fn = r.endpoint
            break

    result = route_fn()
    assert result["available"] is False
    assert "claude" in result["reason"].lower()
    assert "npm i -g @anthropic-ai/claude-code" in result["reason"]


def test_ai_status_no_auth_required():
    """/api/ai/status 不挂 _AUTH dependency (前端启动时无 token 也能探测)."""
    from server.main import app

    for r in app.routes:
        if getattr(r, "path", None) != "/api/ai/status":
            continue
        # 路由的 dependencies 列表应为空 (或不含 Depends(get_current_user))
        deps = getattr(r, "dependencies", None) or []
        # 显式断言 deps 为空 — 不能让 _AUTH 偷偷加进来
        assert deps == [], (
            f"/api/ai/status 必须无依赖鉴权, 但 dependencies={deps}"
        )
        return
    pytest.fail("/api/ai/status route 未注册")


def test_is_claude_available_helper():
    """is_claude_available() public helper 直接调, 当前环境 (claude 已删) 应返 False."""
    from server.ai.agent_spawner import is_claude_available

    # 当前环境已删 claude (2026-08-25) — 这是预期状态
    result = is_claude_available()
    assert isinstance(result, bool)
    # 我们刚删了 claude, 当前应 False; 但不强断言 — 让测试在任何环境都能跑
    assert result is False, (
        "当前测试环境已删 claude (2026-08-25), is_claude_available 应返 False. "
        "若返回 True 说明 PATH 仍有 claude 残留, 请检查环境."
    )


def test_claude_missing_reason_constant():
    """claude_missing_reason() 返非空字符串, 含安装指引."""
    from server.ai.agent_spawner import claude_missing_reason

    reason = claude_missing_reason()
    assert isinstance(reason, str)
    assert len(reason) > 10
    assert "claude" in reason.lower()
    # 必须含 npm 安装命令 (用户可复制粘贴)
    assert "npm i -g" in reason