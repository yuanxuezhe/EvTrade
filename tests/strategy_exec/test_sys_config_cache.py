"""
test_sys_config_cache.py — strategy_exec.data_access.sys_config 单测

覆盖:
  Case 1: 缓存 hit (5s 内不重打 DB)
  Case 2: 缓存 expiry (5s 后重打 DB)
  Case 3: 缺失 key 返 default
  Case 4: invalidate 清缓存
  Case 5: DB 错误返 default (不抛)

策略:
  - 不连 DB (用 monkeypatch _db_read 替代, 不依赖 MySQL)
"""
import time
from unittest.mock import patch

import pytest

from strategy_exec.data_access import sys_config as sc
from strategy_exec.data_access.sys_config import (
    invalidate,
    read,
    reset_for_test,
)


@pytest.fixture(autouse=True)
def _clean_cache():
    """每个 test 前清缓存, 避免互相干扰"""
    reset_for_test()
    yield
    reset_for_test()


def test_cache_hit_does_not_query_db():
    """5s 内连续 read 不重打 DB"""
    with patch.object(sc, "_db_read", return_value="1") as fake_db:
        a = read("his_hq_test_mode", "0")
        b = read("his_hq_test_mode", "0")
        c = read("his_hq_test_mode", "0")
        assert a == "1"
        assert b == "1"
        assert c == "1"
        # _db_read 只调了 1 次 (缓存命中)
        assert fake_db.call_count == 1


def test_cache_expiry_triggers_db_read():
    """缓存 5s 后失效, 下次 read 重打 DB"""
    # 注入更短的 TTL (绕过 5s 等待)
    with patch.object(sc, "_db_read", return_value="0") as fake_db, \
         patch.object(sc, "_CACHE_TTL_S", 0.1):
        assert read("his_hq_test_mode", "0") == "0"
        # 0.1s 内仍 hit
        time.sleep(0.05)
        assert read("his_hq_test_mode", "0") == "0"
        assert fake_db.call_count == 1
        # 0.1s 后 expiry
        time.sleep(0.15)
        assert read("his_hq_test_mode", "0") == "0"
        assert fake_db.call_count == 2


def test_missing_key_returns_default():
    """DB 返 None (key 不存在) → 返 default"""
    with patch.object(sc, "_db_read", return_value=None):
        v = read("nonexistent_key", "fallback")
        assert v == "fallback"


def test_db_error_returns_default_no_raise():
    """DB 异常 (连接失败) → 返 default 不抛"""
    def raise_conn_error(*a, **kw):
        raise RuntimeError("DB connection refused")
    with patch.object(sc, "_db_read", side_effect=raise_conn_error):
        v = read("his_hq_test_mode", "0")
        assert v == "0", "DB 错误应返 default, 不抛"


def test_invalidate_clears_cache():
    """invalidate() 后下次 read 重打 DB"""
    with patch.object(sc, "_db_read", side_effect=["1", "0"]) as fake_db:
        assert read("his_hq_test_mode", "0") == "1"
        assert fake_db.call_count == 1
        # 缓存中, 不会重打
        assert read("his_hq_test_mode", "0") == "1"
        assert fake_db.call_count == 1
        # invalidate 后重打
        invalidate("his_hq_test_mode")
        assert read("his_hq_test_mode", "0") == "0"
        assert fake_db.call_count == 2


def test_invalidate_all_clears_everything():
    """invalidate(None) 清全部缓存 → 下次 read 重打 DB"""
    with patch.object(sc, "_db_read", return_value="1") as fake_db:
        assert read("key_a", "0") == "1"
        assert read("key_b", "0") == "1"
        assert fake_db.call_count == 2  # 2 次首次读
        # 缓存中, 不会重打
        assert read("key_a", "0") == "1"
        assert fake_db.call_count == 2
        # invalidate(None) 清全部
        invalidate(None)
        assert read("key_a", "0") == "1"  # invalidate 后重打, call_count +1
        assert fake_db.call_count == 3
        assert read("key_b", "0") == "1"  # 同理
        assert fake_db.call_count == 4


def test_different_keys_isolated():
    """不同 key 缓存独立"""
    with patch.object(sc, "_db_read", side_effect=["1", "2"]) as fake_db:
        assert read("key_a", "0") == "1"
        assert read("key_b", "0") == "2"
        # invalidate(key_a) 不影响 key_b
        invalidate("key_a")
        with patch.object(sc, "_db_read", return_value="3"):
            assert read("key_a", "0") == "3"
        # key_b 仍在缓存
        assert read("key_b", "0") == "2"