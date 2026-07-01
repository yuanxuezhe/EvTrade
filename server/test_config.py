"""
test_config.py — server/config.py 配置验证器单测

覆盖 ConfigValidator 的 4 个校验分支：
- JWT_SECRET 缺失（无 env 也无 .secret_key）→ 警告 + auto-gen
- RABBITMQ_URL 缺失 → error
- RPC_TIMEOUT 异常（<=0 或 >300）→ 警告
- API_PORT 越界（<1 或 >65535）→ error

注：ConfigValidator 是 dataclass Settings 之上的额外校验层。
Settings 是 frozen=True，测试用 object.__setattr__ 绕过冻结。
JWT_SECRET auto-gen 路径已在 security.py 实现（secrets.token_urlsafe + 持久化）。
"""
import os
import sys

import pytest


def _import_config():
    """延迟 import：避免被 conftest 的 server.* 预加载影响"""
    if "server.config" in sys.modules:
        return sys.modules["server.config"]
    from server import config
    return config


def _set_frozen(cfg, **kwargs):
    """绕过 dataclass frozen=True 设置字段值"""
    for k, v in kwargs.items():
        object.__setattr__(cfg.settings, k, v)


def test_validator_warns_when_no_jwt_secret_and_no_file(tmp_path, monkeypatch):
    """缺 EVTRADE_SECRET env 且 .secret_key 文件不存在 → 警告 + 不会 error"""
    cfg = _import_config()
    monkeypatch.setattr(cfg, "_secret_path", lambda: str(tmp_path / "no_such_file"))
    monkeypatch.delenv("EVTRADE_SECRET", raising=False)

    v = cfg.ConfigValidator()
    passed = v.validate()

    assert any("EVTRADE_SECRET" in w for w in v.warnings)
    assert passed is True


def test_validator_errors_when_rabbitmq_url_empty(monkeypatch):
    """RABBITMQ_URL 为空 → error"""
    cfg = _import_config()
    _set_frozen(cfg, RABBITMQ_URL="")

    v = cfg.ConfigValidator()
    passed = v.validate()
    assert any("RABBITMQ_URL" in e for e in v.errors)
    assert passed is False


def test_validator_warns_when_rpc_timeout_out_of_range(monkeypatch):
    """RPC_TIMEOUT <=0 或 >300 → 警告（不是 error）"""
    cfg = _import_config()
    for bad in (0, -1, 301, 9999):
        _set_frozen(cfg, RPC_TIMEOUT=float(bad))
        v = cfg.ConfigValidator()
        v.validate()
        assert any("RPC_TIMEOUT" in w for w in v.warnings), f"timeout={bad} 应触发警告"


def test_validator_errors_when_api_port_out_of_range(monkeypatch):
    """API_PORT 越界 → error"""
    cfg = _import_config()
    for bad in (0, -1, 65536, 99999):
        _set_frozen(cfg, API_PORT=bad)
        v = cfg.ConfigValidator()
        passed = v.validate()
        assert any("INVALID_API_PORT" in e for e in v.errors), f"port={bad} 应触发 error"
        assert passed is False


def test_validator_passes_with_default_settings(monkeypatch):
    """默认配置（默认 URL + 合理 timeout + 8000 端口）→ 通过"""
    cfg = _import_config()
    _set_frozen(
        cfg,
        RABBITMQ_URL="amqp://test:5672/",
        RPC_TIMEOUT=30.0,
        API_PORT=8000,
    )
    v = cfg.ConfigValidator()
    passed = v.validate()
    assert passed is True
    assert v.errors == []


def test_validate_config_raises_on_errors(monkeypatch):
    """validate_config() 在有 errors 时 raise RuntimeError"""
    cfg = _import_config()
    _set_frozen(cfg, RABBITMQ_URL="")
    with pytest.raises(RuntimeError, match="Config validation failed"):
        cfg.validate_config()