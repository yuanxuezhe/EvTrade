"""
test_short_name.py — REQ-STOCK-007 to_short_name 单元测试

v129.2 (2026-08-13): ASCII run (ETF/50ETF) 整串保留, 不再被 s[0] 截断。
覆盖:
- 纯汉字 → 拼音首字母
- ETF / 50ETF / 数字串 → 整串保留大写
- ST 前缀 (大小写归一 + 保留)
- 空/None/空白 → ""
"""
import pytest

from server.services.short_name import to_short_name


def test_pure_chinese_uses_pinyin_initials():
    """纯汉字 → 拼音首字母大写."""
    assert to_short_name("平安银行") == "PAYH"
    assert to_short_name("贵州茅台") == "GZMT"


def test_etf_run_kept_whole():
    """v129.2: 名称里的 ETF 整串保留, 不只留 E."""
    assert to_short_name("创业板ETF") == "CYBETF"
    assert to_short_name("银行ETF") == "YHETF"


def test_digit_letter_run_kept_whole():
    """数字+字母连续串 (50ETF/300ETF) 整串保留, 不只留首字符."""
    assert to_short_name("华夏上证50ETF") == "HXSZ50ETF"
    assert to_short_name("沪深300ETF") == "HS300ETF"


def test_single_ascii_letter_kept():
    """单个字母 (如 A 股后缀) 行为不变."""
    assert to_short_name("京东方A") == "JDFA"


def test_st_prefix_normalized_and_kept():
    """ST/*ST 前缀保留, 大小写归一."""
    assert to_short_name("ST华微") == "STHW"
    assert to_short_name("*ST实达") == "*STSD"
    assert to_short_name("*st康佳") == "*STKJ"


def test_mixed_with_st_and_etf():
    """ST 前缀 + 主体含 ASCII run 组合."""
    assert to_short_name("ST银华日利ETF") == "STYHRLETF"


def test_truncate_to_16():
    """超 16 字符截断."""
    long_name = "华夏上证50ETF联接基金A"  # 10 汉字 + 50ETF + 联接基金A → 超过 16
    assert len(to_short_name(long_name)) <= 16


def test_empty_inputs_return_empty():
    """空 / None / 全空白 → 空字符串."""
    assert to_short_name("") == ""
    assert to_short_name(None) == ""
    assert to_short_name("   ") == ""
