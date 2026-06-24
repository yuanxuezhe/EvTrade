"""
parsers_common.py — 通用响应解析工具

应答协议（柜台返回）：
  - 第 1 结果集：固定两字段 code / msg，1 行
      * code == 0 表示成功；其他值表示业务错误
      * msg  为人类可读的错误描述
  - 第 2 结果集：业务数据，0..N 行（仅当 code == 0 时才有意义）

本模块提供：
- _select_rs: 安全切换结果集（1-based，兼容两种 msgpacket API 风格）
- _parse_code_msg: 读第 1 结果集的 code/msg
- _iter_rows: 把第 rs 个结果集按 headers 解析成 dict 数组
- _to_float / _to_int: 安全类型转换
- _empty: 构造 code != 0 时的空响应

业务特定解析器（_parse_asset / _parse_orders / ...）在 parsers_business.py。
"""
from typing import Any, Dict

from msgpacket import MsgPacket


def _select_rs(pkt: MsgPacket, rs: int) -> bool:
    """安全切换到第 rs 个结果集（1-based）。

    优先使用 select_result_set(rs)；某些 msgpacket 版本在该 API 异常时，
    回退到 reset → next_result_set 的链式定位。返回是否成功。
    """
    try:
        ok = pkt.select_result_set(rs)
        if ok is False:
            return False
        # 部分实现 select_result_set 不返回 bool，按当前 rs 校验
        try:
            return pkt.result_set() == rs
        except Exception:
            return True
    except Exception:
        pass
    # fallback
    try:
        pkt.select_result_set(1)
    except Exception:
        pass
    cur = 1
    while cur < rs:
        if not pkt.next_result_set():
            return False
        cur += 1
    return True


def _parse_code_msg(pkt: MsgPacket) -> tuple:
    """读取第 1 结果集中的 code/msg。失败时返回 (-1, str)。"""
    if pkt.result_set_count() < 1:
        return -1, "empty packet"
    if not _select_rs(pkt, 1):
        return -1, "missing result set #1"
    pkt.reset_cursor()
    if not pkt.fetch_next():
        return -1, "missing code row"
    raw_code = (pkt.get_value_str("code") or "").strip()
    raw_msg = (pkt.get_value_str("msg") or "").strip()
    try:
        code = int(raw_code) if raw_code else -1
    except ValueError:
        code = -1
    return code, raw_msg


def _iter_rows(pkt: MsgPacket, rs: int) -> list:
    """把第 rs 个结果集的所有行按 headers 解析为 dict 数组。

    不做类型转换，由调用方按业务再做映射。
    若第 rs 个结果集不存在，返回空数组。
    """
    if pkt.result_set_count() < rs:
        return []
    if not _select_rs(pkt, rs):
        return []
    headers_str = pkt.get_headers() or ""
    headers = [h.strip() for h in headers_str.split(",") if h.strip()]
    rows: list = []
    pkt.reset_cursor()
    while pkt.fetch_next():
        rows.append({h: (pkt.get_value_str(h) or "") for h in headers})
    return rows


def _to_float(v: str) -> float:
    try:
        return float(v) if v else 0.0
    except (TypeError, ValueError):
        return 0.0


def _to_int(v: str) -> int:
    try:
        return int(v) if v else 0
    except (TypeError, ValueError):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return 0


def _empty(code: int, msg: str) -> Dict[str, Any]:
    return {"code": code, "msg": msg, "list": []}
