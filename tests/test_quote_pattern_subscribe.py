#!/usr/bin/env python3
"""2026-07-10 quote-pattern-subscribe 单元测试

覆盖 match_pattern 规则 + WSManager.subscribe 索引 + get_subscribers pattern 遍历
"""
import sys
import unittest
from pathlib import Path

# 让 import server.* 能工作
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.ws.manager import match_pattern, WSManager


class FakeWebSocket:
    """最小 ws mock（broadcast_to_stock 不需要 send_json）"""
    pass


class TestMatchPattern(unittest.TestCase):
    """子串匹配规则: pattern in stock_code"""

    def test_empty_matches_everything(self):
        self.assertTrue(match_pattern("000001.SZ", ""))
        self.assertTrue(match_pattern("600000.SH", ""))
        self.assertTrue(match_pattern("anything", ""))

    def test_market_SU(self):
        # "SZ" 是 "000001.SZ" 的子串 (在末尾)
        self.assertTrue(match_pattern("000001.SZ", "SZ"))
        # "SZ" 不是 "600000.SH" 的子串
        self.assertFalse(match_pattern("600000.SH", "SZ"))

    def test_market_SH(self):
        self.assertTrue(match_pattern("600000.SH", "SH"))
        self.assertFalse(match_pattern("000001.SZ", "SH"))

    def test_substring_digits(self):
        # "000001" 是 "000001.SZ" 和 "000001.SH" 的子串
        self.assertTrue(match_pattern("000001.SZ", "000001"))
        self.assertTrue(match_pattern("000001.SH", "000001"))

    def test_exact_stock_code(self):
        self.assertTrue(match_pattern("000001.SZ", "000001.SZ"))
        self.assertFalse(match_pattern("000001.SH", "000001.SZ"))
        self.assertFalse(match_pattern("000002.SZ", "000001.SZ"))

    def test_substring_not_equal(self):
        # '000001.SZ' 不是 '000001.SZXXX' 的子串 - 错, 它是
        self.assertTrue(match_pattern("000001.SZXXX", "000001.SZ"))
        # 'SZ' 在 'XSZ' 里也是子串
        self.assertTrue(match_pattern("XSZ", "SZ"))


class TestWSManagerPattern(unittest.TestCase):
    """WSManager pattern 化索引"""

    def setUp(self):
        self.mgr = WSManager()
        self.ws_a = FakeWebSocket()
        self.ws_b = FakeWebSocket()

    def test_subscribe_empty_string_wildcard(self):
        """空字符串 = 全市场"""
        accepted = self.mgr.subscribe(self.ws_a, [""])
        self.assertEqual(accepted, {""})
        self.assertIn("", self.mgr.subscriber_index[self.ws_a])

    def test_subscribe_market_pattern(self):
        accepted = self.mgr.subscribe(self.ws_a, ["SZ", "SH"])
        self.assertEqual(accepted, {"SZ", "SH"})
        self.assertEqual(self.mgr.subscriber_index[self.ws_a], {"SZ", "SH"})

    def test_subscribe_mixed_patterns(self):
        accepted = self.mgr.subscribe(
            self.ws_a, ["000001.SZ", "SZ", "", "000001"]
        )
        self.assertEqual(accepted, {"000001.SZ", "SZ", "", "000001"})

    def test_get_subscribers_wildcard_matches_all(self):
        """空 pattern 订阅者接收所有 stock_code 的 tick"""
        self.mgr.subscribe(self.ws_a, [""])
        subs = self.mgr.get_subscribers("000001.SZ")
        self.assertIn(self.ws_a, subs)
        subs = self.mgr.get_subscribers("600000.SH")
        self.assertIn(self.ws_a, subs)
        subs = self.mgr.get_subscribers("any.weird.code")
        self.assertIn(self.ws_a, subs)

    def test_get_subscribers_market_pattern(self):
        """'SZ' 订阅者只接收 SZ 市场 tick（子串匹配）"""
        self.mgr.subscribe(self.ws_a, ["SZ"])
        # 含 SZ 子串的 code 都匹配
        self.assertIn(self.ws_a, self.mgr.get_subscribers("000001.SZ"))
        self.assertIn(self.ws_a, self.mgr.get_subscribers("a-SZ-b"))  # 子串匹配
        # 不含 SZ 的 code 不匹配
        self.assertNotIn(self.ws_a, self.mgr.get_subscribers("600000.SH"))
        self.assertNotIn(self.ws_a, self.mgr.get_subscribers("000001"))

    def test_get_subscribers_exact_pattern(self):
        """精确 stock_code 只匹配该 code"""
        self.mgr.subscribe(self.ws_a, ["000001.SZ"])
        self.assertIn(self.ws_a, self.mgr.get_subscribers("000001.SZ"))
        self.assertNotIn(self.ws_a, self.mgr.get_subscribers("000002.SZ"))

    def test_get_subscribers_combined(self):
        """多个 pattern 组合 OR 匹配"""
        self.mgr.subscribe(self.ws_a, ["SZ", "000001"])
        self.mgr.subscribe(self.ws_b, [""])
        subs = self.mgr.get_subscribers("000001.SZ")
        self.assertIn(self.ws_a, subs)  # SZ + 000001 都匹配
        self.assertIn(self.ws_b, subs)  # '' 永远匹配
        subs = self.mgr.get_subscribers("600000.SH")
        self.assertNotIn(self.ws_a, subs)  # SZ 不匹配 SH, 000001 不匹配 600000
        self.assertIn(self.ws_b, subs)  # '' 匹配

    def test_unsubscribe_pattern(self):
        self.mgr.subscribe(self.ws_a, ["SZ", "", "000001.SZ"])
        removed = self.mgr.unsubscribe(self.ws_a, ["SZ"])
        self.assertEqual(removed, {"SZ"})
        self.assertEqual(self.mgr.subscriber_index[self.ws_a], {"", "000001.SZ"})

    def test_unsubscribe_only_what_subscribed(self):
        self.mgr.subscribe(self.ws_a, ["SZ"])
        removed = self.mgr.unsubscribe(self.ws_a, ["", "SH"])
        self.assertEqual(removed, set())  # 都不在订阅里

    def test_clear_ws(self):
        self.mgr.subscribe(self.ws_a, ["", "SZ", "000001.SZ"])
        self.mgr.clear_ws(self.ws_a)
        self.assertNotIn(self.ws_a, self.mgr.subscriber_index)
        self.assertEqual(self.mgr.subscription_index, {})

    def test_max_subscriptions_limit(self):
        """MAX_SUBSCRIPTIONS_PER_WS=200 限制"""
        pats = [f"code_{i:04d}" for i in range(199)]
        self.mgr.subscribe(self.ws_a, pats)
        with self.assertRaises(ValueError):
            self.mgr.subscribe(self.ws_a, ["extra1", "extra2", "extra3"])

    def test_pattern_dedup(self):
        """重复 pattern 幂等"""
        accepted = self.mgr.subscribe(self.ws_a, ["SZ", "SZ", "SZ"])
        self.assertEqual(accepted, {"SZ"})
        self.assertEqual(self.mgr.subscriber_index[self.ws_a], {"SZ"})

    def test_pattern_with_whitespace_stripped(self):
        accepted = self.mgr.subscribe(self.ws_a, [" SZ ", "  000001.SZ  "])
        self.assertEqual(accepted, {"SZ", "000001.SZ"})

    def test_empty_string_preserved(self):
        """空字符串不被 strip 掉 (strip('') = '' 仍为空)"""
        accepted = self.mgr.subscribe(self.ws_a, [""])
        self.assertIn("", accepted)


if __name__ == "__main__":
    unittest.main(verbosity=2)