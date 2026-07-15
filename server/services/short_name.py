"""
server/services/short_name.py — 股票 short_name 自动生成 (v46+ short-name-auto)

REQ-STOCK-007:
- 拼音首字母转大写
- ST 前缀 (*ST / ST, 大小写不敏感) 保留到 short_name 开头
- 16 字符上限
- 失败 / 空字符串 返回 ""

调用方:
- server/repo/stocks.py::create_by_admin  →  新增时自动算
- server/repo/stocks.py::update_by_admin  →  stock_name 改动时自动重算
- server/scripts/backfill_short_name.py  →  v25 已 backfill, 仅复用本函数
"""

from typing import Optional

from pypinyin import lazy_pinyin


def to_short_name(stock_name: Optional[str]) -> str:
    """根据 stock_name 生成 short_name (拼音首字母 + ST 前缀保留)

    例:
      平安银行    → PAYH
      贵州茅台    → GZMT
      *ST实达     → *STSD
      ST华微      → STHW
      *st康佳     → *STKJ    (大小写归一化)
      st美丽      → STMЛ     (大小写归一化)
      "" / None   → ""

    Args:
        stock_name: 股票中文名 (可能含 ST/*ST 前缀)

    Returns:
        拼音首字母大写 (≤16 字符), 空字符串表示无 stock_name 或转换失败
    """
    if not stock_name:
        return ""

    name = stock_name.strip()
    if not name:
        return ""

    # 1. 检测 ST 前缀 (大小写不敏感)
    prefix = ""
    lower_name = name.lower()
    if lower_name.startswith("*st"):
        prefix = "*ST"
        name = name[3:].strip()
    elif lower_name.startswith("st"):
        prefix = "ST"
        name = name[2:].strip()

    if not name:
        # 只有 ST 前缀, 没实质内容, 返回空 (不应发生, 但防御性)
        return ""

    try:
        # 2. pypinyin 转每个字符首字母 (字母 / 数字保留本身)
        initials = [s[0] for s in lazy_pinyin(name) if s]
        result = prefix + "".join(initials).upper()
        return result[:16]
    except Exception:
        # 3. 失败 fallback 返回空字符串 (不阻塞主流程)
        return ""
