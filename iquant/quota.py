#encoding: gbk
"""
QMT tick publisher: 批量 UDP 发送 (Buffer + 双触发:50 条 OR 4KB OR 200ms 定时器)。

协议 (v1.1 batch 模式):
  - 单帧 UDP datagram = N 条 tick 拼接 (1 <= N <= QUOTA_BATCH_MAX)
  - tick 之间用 ',' 分隔; 字段内仍用 '|' 分隔 (向后兼容)
  - 帧内禁止出现 ',', 所有 32 字段值 (数字/ASCII) 已天然不包含 ','

触发条件 (满足任一即 flush):
  1. 累积 tick 数 >= QUOTA_BATCH_MAX (默认 50)
  2. 估算帧字节数 > QUOTA_MAX_FRAME_BYTES (默认 4096, 防 UDP 分片)
  3. 自上次 flush 起 QUOTA_FLUSH_MS ms (默认 200, 防慢市延迟无限累积)
"""
import os
import socket
import threading
import time
import traceback
from collections import deque

# ================================================================
# 1. Config
# ================================================================
class Config:
    UDP_HOST = os.environ.get("QUOTA_UDP_HOST", "192.168.10.2")
    UDP_PORT = int(os.environ.get("QUOTA_UDP_PORT", "9001"))

    # ---- batch 调优参数 (opsx 子任务 1: 安全侧默认) ----
    # QUOTA_BATCH_MAX 条 tick × 每条 ~150B + 50 个 ',' ≈ 7600B, 取 8192B 保证 size 阈值先触发
    QUOTA_BATCH_MAX = int(os.environ.get("QUOTA_BATCH_MAX", "50"))
    QUOTA_FLUSH_MS = int(os.environ.get("QUOTA_FLUSH_MS", "200"))
    QUOTA_MAX_FRAME_BYTES = int(os.environ.get("QUOTA_MAX_FRAME_BYTES", "8192"))

config = Config()

# 全局原生 UDP 套接字（进程级别单例）
_udp_sock = None
_target_addr = (config.UDP_HOST, config.UDP_PORT)

# ================================================================
# 1.5 Batch Buffer (子任务 1)
# ================================================================
class _BatchBuffer:
    """双触发批量缓冲: size / bytes / timer 三阈值。

    - on_quote 回调线程: enqueue() 入队, 触发立即 flush 判定
    - 后台 timer 线程: 每 QUOTA_FLUSH_MS 扫描, 超时强制 flush
    - 锁粒度: 仅保护 deque 头部与计数器, 临界区 < 10us
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._buf = deque()          # 元素: 已编码的 tick bytes (gbk)
        self._byte_len = 0           # 估算帧字节数 (含 ',' 分隔符)
        self._last_flush_ts = time.monotonic()
        self._timer = None

    def _start_timer(self):
        """启动后台定时器 (首次入队时调用一次, 之后由 timer 自我重启)。"""
        if self._timer is not None and self._timer.is_alive():
            return
        self._timer = threading.Thread(target=self._timer_loop, daemon=True)
        self._timer.start()

    def _timer_loop(self):
        """后台守护线程: 每 QUOTA_FLUSH_MS 扫描一次, 触发 timeout flush。"""
        interval_s = config.QUOTA_FLUSH_MS / 1000.0
        while True:
            time.sleep(interval_s)
            with self._lock:
                if not self._buf:
                    # 空队列: 退出 timer, 下次 enqueue 再启动
                    return
                if (time.monotonic() - self._last_flush_ts) * 1000 >= config.QUOTA_FLUSH_MS:
                    self._flush_locked()

    def enqueue(self, line: bytes):
        """on_quote 回调调用: 入队 + 三阈值判定。"""
        with self._lock:
            self._buf.append(line)
            # 估算帧字节数: len(line) + 1 (',')
            self._byte_len += len(line) + 1
            self._start_timer()

            # 阈值 1: tick 数 >= 50
            # 阈值 2: 帧字节数 > 4KB (防 UDP 分片)
            if (len(self._buf) >= config.QUOTA_BATCH_MAX
                    or self._byte_len > config.QUOTA_MAX_FRAME_BYTES):
                self._flush_locked()
            # 阈值 3: timer 负责

    def _flush_locked(self):
        """临界区内: 弹出所有 tick, ',' join, sendto。"""
        if not self._buf:
            return
        frame = b",".join(self._buf)
        self._buf.clear()
        self._byte_len = 0
        self._last_flush_ts = time.monotonic()
        # sendto 必须放锁外 (网络 IO 可能阻塞, 会卡住 enqueue)
        # 用 list 把目标传出, 释放锁后再发
        _pending_frames.append(frame)

    def flush_now(self):
        """外部强制 flush (stop / 调试用)。"""
        with self._lock:
            self._flush_locked()

# 全局: 缓冲 + 待发送帧队列 (锁外异步发送)
_buffer = _BatchBuffer()
_pending_frames = deque()  # 锁外线程安全的 append/sendto 队列
_pending_lock = threading.Lock()
_sender_started = False
_sender_lock = threading.Lock()


def _ensure_sender():
    """启动常驻 sender 线程 (只起一次), 轮询 _pending_frames 执行 sendto。

    为什么必须常驻: 定时器 flush 出来的 frame 必须有线程来 sendto,
    否则即使 buffer 触发了 flush, 数据也只躺在 _pending_frames 里不出去。
    """
    global _sender_started
    with _sender_lock:
        if _sender_started:
            return
        _sender_started = True

    def _loop():
        while True:
            with _pending_lock:
                if not _pending_frames:
                    # 没数据就睡一会, 避免空转 CPU
                    time.sleep(0.001)
                    continue
                frame = _pending_frames.popleft()
            # 等 socket 就绪 (test fixture 可能先于 init 完成, 或临时网络抖动)
            sock = None
            for _ in range(100):
                sock = _udp_sock
                if sock is not None:
                    break
                time.sleep(0.001)
            else:
                # 100ms 还没 socket, 放弃这帧 (避免积压)
                continue
            try:
                sock.sendto(frame, _target_addr)
            except Exception as e:
                print(f"[sender Send Error] {e}", flush=True)

    t = threading.Thread(target=_loop, daemon=True, name="quota-sender")
    t.start()


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
            # 加大系统发送缓存
            _udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
            print(f"[Init] Direct UDP Socket initialized -> {_target_addr}", flush=True)
    except Exception as e:
        print(f"[Init Error] Failed to create UDP socket: {e}", flush=True)

    # 启动常驻 sender 线程 (批量模式下, 定时器 flush 的帧必须有线程 sendto)
    _ensure_sender()

    # 订阅行情
    ContextInfo.subscribe_whole_quote(["SZ", "SH"], on_quote)


def on_quote(datas) -> None:
    global _udp_sock
    if _udp_sock is None:
        return

    try:
        lines = format_quote(datas)
        # 批量入队: 由 _BatchBuffer 判定 50 条 / 4KB / 200ms 三阈值
        # 常驻 sender 线程负责 sendto (见 _ensure_sender)
        for line in lines:
            _buffer.enqueue(line)
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
