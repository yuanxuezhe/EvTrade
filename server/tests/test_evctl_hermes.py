"""
test_evctl_hermes.py — scripts/evctl.py hermes 服务接入 (2026-08-23, hermes-serve-evctl)

覆盖:
- SERVICES['hermes'] 端口/HERMES_PORT/DEFAULT_SERVICES 接线
- _hermes_cmd() 构造 (hermes CLI 缺失时不 crash, 回落 'hermes')
- _hermes_preflight() (callable 预检): PATH 无 hermes → False
- _preflight_check() 支持 callable 预检项 (与 module import 检查并存)
"""
import importlib.util

import pytest


def _load_evctl():
    """importlib 加载 scripts/evctl.py (scripts/ 无 __init__.py, 非包)."""
    spec = importlib.util.spec_from_file_location('evctl', 'scripts/evctl.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


evctl = _load_evctl()


def test_hermes_in_default_services_with_port():
    """hermes 进 DEFAULT_SERVICES, SERVICES 表端口 = 9119."""
    assert 'hermes' in evctl.DEFAULT_SERVICES
    svc = evctl.SERVICES['hermes']
    assert svc.name == 'hermes'
    assert svc.port == evctl.HERMES_PORT == 9119
    # preflight 是 callable (函数), 不是 module 名
    assert callable(svc.preflight[0])


def test_hermes_cmd_falls_back_when_cli_missing(monkeypatch):
    """PATH 无 hermes → _hermes_cmd() 回落 'hermes' (不 crash)."""
    monkeypatch.setattr(evctl.shutil, 'which', lambda name: None)
    cmd = evctl._hermes_cmd()
    assert cmd == ['hermes', 'serve']


def test_hermes_cmd_uses_resolved_path(monkeypatch):
    """PATH 有 hermes → 用真实可执行路径."""
    monkeypatch.setattr(evctl.shutil, 'which', lambda name: '/usr/local/bin/hermes')
    cmd = evctl._hermes_cmd()
    assert cmd == ['/usr/local/bin/hermes', 'serve']


def test_hermes_preflight_false_when_missing(monkeypatch):
    """PATH 无 hermes → preflight False (并输出安装指引)."""
    monkeypatch.setattr(evctl.shutil, 'which', lambda name: None)
    assert evctl._hermes_preflight() is False


def test_hermes_preflight_true_when_present(monkeypatch):
    """PATH 有 hermes → preflight True."""
    monkeypatch.setattr(evctl.shutil, 'which', lambda name: '/usr/local/bin/hermes')
    assert evctl._hermes_preflight() is True


def test_preflight_check_supports_callable(monkeypatch):
    """_preflight_check 对 callable 预检项返回其布尔结果."""
    svc = evctl.Service('fake', 9999, '.', ['echo'],
                        preflight=[lambda: True])
    assert evctl._preflight_check(svc) is True

    svc_bad = evctl.Service('fake2', 9999, '.', ['echo'],
                            preflight=[lambda: False])
    assert evctl._preflight_check(svc_bad) is False


def test_preflight_check_keeps_module_import_branch():
    """既有 module import 预检不受影响 (hermes 的 _preflight_check 分支并存)."""
    svc = evctl.Service('fake3', 9999, '.', ['echo'],
                        preflight=['os'])  # os 一定可 import
    assert evctl._preflight_check(svc) is True

    svc_missing = evctl.Service('fake4', 9999, '.', ['echo'],
                                preflight=['__definitely_not_a_module_xyz__'])
    assert evctl._preflight_check(svc_missing) is False


def test_start_hermes_returns_false_when_cli_missing(monkeypatch):
    """start_service(hermes) 在 CLI 缺失时返回 False (preflight 拦截)."""
    monkeypatch.setattr(evctl.shutil, 'which', lambda name: None)
    svc = evctl.SERVICES['hermes']
    assert evctl.start_service(svc) is False
