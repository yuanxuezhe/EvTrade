#encoding: gbk
"""
QMT tick publisher: Direct UDP send in on_quote callback (No Queue, No Threads).
"""
import os
import socket
import traceback

# ================================================================
# 1. Config
# ================================================================
class Config:
    UDP_HOST = os.environ.get("QUOTA_UDP_HOST", "192.168.10.2")
    UDP_PORT = int(os.environ.get("QUOTA_UDP_PORT", "9001"))

config = Config()

# 全局原生 UDP 套接字（进程级别单例）
_udp_sock = None
_target_addr = (config.UDP_HOST, config.UDP_PORT)


def safe_get(lst, idx, default=0):
    """安全获取数组指定下标元素，防御 IndexError"""
    if isinstance(lst, (list, tuple)) and len(lst) > idx:
        return lst[idx]
    return default


def format_quote(datas) -> list:
    """格式化行情数据为 GBK 字节串"""
    def fmt_price(v) -> str:
        try:
            s = f"{float(v):.4f}".rstrip("0").rstrip(".")
            return s if s else "0"
        except (ValueError, TypeError):
            return "0"

    out = []
    for code, q in datas.items():
        if not isinstance(q, dict):
            continue

        ask_prices = q.get("askPrice", [])
        bid_prices = q.get("bidPrice", [])
        ask_vols = q.get("askVol", [])
        bid_vols = q.get("bidVol", [])

        fields = [
            code,
            q.get("stime", ""),
            fmt_price(q.get("lastPrice", 0)),
            fmt_price(q.get("open", 0)),
            fmt_price(q.get("high", 0)),
            fmt_price(q.get("low", 0)),
            fmt_price(q.get("lastClose", 0)),
            fmt_price(q.get("volume", 0)),
            fmt_price(q.get("amount", 0)),
            fmt_price(q.get("openInt", 0)),
            fmt_price(q.get("transactionNum", 0)),
        ]

        # 买卖 5 档
        for i in range(5):
            fields.append(fmt_price(safe_get(ask_prices, i, 0)))
        for i in range(5):
            fields.append(fmt_price(safe_get(bid_prices, i, 0)))
        for i in range(5):
            fields.append(fmt_price(safe_get(ask_vols, i, 0)))
        for i in range(5):
            fields.append(fmt_price(safe_get(bid_vols, i, 0)))

        out.append("|".join(map(str, fields)).encode("gbk"))
    return out


# ================================================================
# QMT External Callbacks
# ================================================================
def init(ContextInfo) -> None:
    global _udp_sock
    try:
        # 初始化全局 UDP Socket
        if _udp_sock is None:
            _udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # 扩大系统发送缓冲区
            _udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
            print(f"[Init] Direct UDP Socket initialized -> {_target_addr}", flush=True)
    except Exception as e:
        print(f"[Init Error] Failed to create UDP socket: {e}", flush=True)

    # 订阅行情
    etfs = list(dict.fromkeys(ContextInfo.get_stock_list_in_sector("中证ETF")))
    if not etfs:
        etfs = list(dict.fromkeys(ContextInfo.get_stock_list_in_sector("沪深A股")))
    print(f"[Init] Subscribed to {len(etfs)} symbols", flush=True)

    ContextInfo.subscribe_whole_quote(["SZ", "SH"], on_quote)


def on_quote(datas) -> None:
    global _udp_sock
    if _udp_sock is None:
        return

    try:
        lines = format_quote(datas)
        # 在回调线程内直接执行 sendto 发送，不经过任何队列或子线程
        for line in lines:
            _udp_sock.sendto(line, _target_addr)
    except Exception as e:
        print(f"[on_quote Send Error] {e}\n{traceback.format_exc()}", flush=True)


def stop(ContextInfo) -> None:
    global _udp_sock
    print("[Stop] Closing Direct UDP Socket...", flush=True)
    if _udp_sock is not None:
        try:
            _udp_sock.close()
        except Exception:
            pass
        _udp_sock = None
    print("[Stop] Closed cleanly", flush=True)
