"""
parsers_push.py — push 消息行提取（simplify-rpc-transport-thin）

职责：从 push 包的 MsgPacket 中提取所有结果集的所有行，header 名 → 字符串值。

与 parsers_common._iter_rows 的差异：
- push 字段名没有统一约定（ord_cfm / trd_cfm 各异），不做类型转换
- 字符串原样交给前端展示层处理
"""
from typing import Any, Dict, List

from msgpacket import MsgPacket


def _iter_push_rows(pkt: MsgPacket) -> List[Dict[str, Any]]:
    """把 push 包里所有结果集的所有行原样取出，header 名 → 字符串值。"""
    rows: List[Dict[str, Any]] = []
    headers_str = pkt.get_headers() or ""
    headers = [h.strip() for h in headers_str.split(",") if h.strip()]

    for rs in range(1, pkt.result_set_count() + 1):
        if rs > 1:
            if not pkt.next_result_set():
                break
        pkt.reset_cursor()
        while pkt.fetch_next():
            row = {h: (pkt.get_value_str(h) or "") for h in headers}
            rows.append(row)
    return rows