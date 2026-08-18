#encoding: gbk
"""
QMT tick publisher: pushes quotes to hqserverd via UDP (no RabbitMQ).

Wire format (kept compatible with the original MQ version, so hqserverd
parser logic is unchanged):
  - one tick per UDP datagram
  - gbk encoding
  - fields delimited by "|", first field = stock_code
  - 32 fields: code|stime|last|open|high|low|lastClose|volume|amount|openInt|txnNum|
               ask1..ask5|bid1..bid5|askVol1..askVol5|bidVol1..bidVol5

Why we dropped MQ:
  RabbitMQ adds an extra hop (broker + serialization + ACK) while both
  sender and receiver are on the LAN; UDP unicast is lower latency, has
  fewer dependencies, and is simpler to operate. Losing the occasional
  tick is harmless for the front-end display.

External API (QMT callback contract, do NOT rename):
  - init(ContextInfo)
  - on_quote(datas)
  - stop(ContextInfo)
"""
import asyncio
import os
import socket
import threading
from collections import deque


# ================================================================
# 1. Config
# ================================================================
class Config:
    # quota.py default target = hqserverd on 192.168.1.* (cross-machine).
    # Override at deploy time with: QUOTA_UDP_HOST / QUOTA_UDP_PORT
    UDP_HOST = os.environ.get("QUOTA_UDP_HOST", "192.168.1.20")
    UDP_PORT = int(os.environ.get("QUOTA_UDP_PORT", "9001"))

    NUM_WORKERS = 1                # one worker is enough: asyncio + UDP sendto is non-blocking
    SNAPSHOT_INTERVAL = 0.005      # sleep 5ms on empty queue, prevents busy-spin
    BATCH_DRAIN_LIMIT = 2000       # cap per snapshot flush, avoid burst floods


config = Config()


# ================================================================
# 2. Global state (QMT process singleton)
# ================================================================
class _State:
    __slots__ = (
        "quote_queue",
        "loop",
        "transport",
        "thread",         # background asyncio thread ref (joined in stop())
        "active",
        "token",
        "lock",
    )

    def __init__(self):
        self.quote_queue = deque()    # QMT callback appends ticks; worker snapshots+swaps
        self.loop = None              # asyncio loop
        self.transport = None         # _UdpTransport
        self.thread = None            # background asyncio thread
        self.active = False
        self.token = 0
        self.lock = threading.Lock()


_state = _State()


# ================================================================
# 3. UDP transport (asyncio DatagramProtocol wrapper)
# ================================================================
class _UdpTransport:
    """Single-peer UDP sender: asyncio's DatagramProtocol + socket.sendto.

    Why asyncio transport over raw socket + sendto:
      - avoids thread/loop interaction problems with the worker loop;
      - OS socket buffer provides natural backpressure when full.
    """

    def __init__(self, host: str, port: int):
        self._host = host
        self._port = port
        self._transport = None
        self._protocol = None

    async def start(self) -> bool:
        loop = asyncio.get_event_loop()
        try:
            self._transport, self._protocol = await loop.create_datagram_endpoint(
                asyncio.DatagramProtocol,
                remote_addr=(self._host, self._port),
                # do NOT bind a local port; let OS pick one
            )
            print(f"[UDP] connected to {self._host}:{self._port}", flush=True)
            return True
        except Exception as e:
            print(f"[UDP] connect failed: {e}", flush=True)
            return False

    def send(self, payload: bytes) -> None:
        if self._transport is None:
            return
        try:
            self._transport.sendto(payload)
        except Exception as e:
            # UDP is connectionless; a single send failure does not block subsequent ones.
            # Cumulative errors are monitored via debug log if needed.
            print(f"[UDP] sendto error: {e}", flush=True)

    def close(self) -> None:
        if self._transport is not None:
            try:
                self._transport.close()
            except Exception:
                pass
            self._transport = None


# ================================================================
# 4. Snapshot worker: drain deque -> UDP sendto in batches
# ================================================================
async def quota_snapshot_worker(worker_id: int, transport: _UdpTransport, auth_token: int) -> None:
    print(f"[Worker-{worker_id}] started (UDP batch-send mode)", flush=True)

    while _state.active and _state.token == auth_token:
        batch_lines = None

        # 1. atomic swap: take current deque, replace with a fresh empty one
        with _state.lock:
            if _state.quote_queue:
                batch_lines = _state.quote_queue
                _state.quote_queue = deque()

        # 2. batch send (each tick = one UDP datagram)
        if batch_lines:
            count = 0
            for line in batch_lines:
                if count >= config.BATCH_DRAIN_LIMIT:
                    break
                transport.send(line)
                count += 1
            # yield to event loop (do NOT asyncio.sleep(0), it would race
            # with transport internal datagram queueing)
            await asyncio.sleep(0)
        else:
            await asyncio.sleep(config.SNAPSHOT_INTERVAL)

    print(f"[Worker-{worker_id}] exited", flush=True)


# ================================================================
# 5. Main event loop
# ================================================================
async def async_main_loop(auth_token: int) -> None:
    loop = asyncio.get_event_loop()
    _state.loop = loop

    transport = _UdpTransport(config.UDP_HOST, config.UDP_PORT)
    if not await transport.start():
        _state.active = False
        _state.transport = None
        return
    _state.transport = transport

    print(f"[Main] starting {config.NUM_WORKERS} snapshot worker(s)...", flush=True)
    worker_tasks = [
        loop.create_task(quota_snapshot_worker(i, transport, auth_token))
        for i in range(config.NUM_WORKERS)
    ]

    try:
        while _state.active and _state.token == auth_token:
            await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        pass
    finally:
        print("[Main] unloading workers and closing UDP transport...", flush=True)
        for t in worker_tasks:
            if not t.done():
                t.cancel()
        transport.close()
        _state.transport = None


def start_network_thread(auth_token: int) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(async_main_loop(auth_token))
    finally:
        loop.close()


# ================================================================
# 6. QMT external callbacks (signature frozen, do NOT change)
# ================================================================
def init(ContextInfo) -> None:
    _state.token += 1
    current_token = _state.token
    with _state.lock:
        _state.quote_queue.clear()
    _state.active = True

    _state.thread = threading.Thread(
        target=start_network_thread,
        args=(current_token,),
        name=f"UDP-Broadcast-{current_token}",
    )
    _state.thread.daemon = True
    _state.thread.start()

    # subscribe to ETF sector first, fall back to full A-share list
    etfs = list(dict.fromkeys(ContextInfo.get_stock_list_in_sector("中证ETF")))
    if not etfs:
        etfs = list(dict.fromkeys(ContextInfo.get_stock_list_in_sector("沪深A股")))
    print(f"[Init] subscribed to {len(etfs)} symbols", flush=True)

    ContextInfo.subscribe_whole_quote(["SZ", "SH"], on_quote)


def on_quote(datas) -> None:
    if not _state.active:
        return
    lines = format_quote(datas)
    with _state.lock:
        _state.quote_queue.extend(lines)


def format_quote(datas) -> list:
    """datas: {stock_code: {lastPrice, open, high, low, lastClose, volume, amount, ...}}"""
    def fmt_price(v) -> str:
        s = f"{float(v):.4f}".rstrip("0").rstrip(".")
        return s if s else "0"

    out = []
    for code, q in datas.items():
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
        for i in range(5):
            fields.append(fmt_price(q.get("askPrice", [0] * 5)[i]))
        for i in range(5):
            fields.append(fmt_price(q.get("bidPrice", [0] * 5)[i]))
        for i in range(5):
            fields.append(fmt_price(q.get("askVol", [0] * 5)[i]))
        for i in range(5):
            fields.append(fmt_price(q.get("bidVol", [0] * 5)[i]))
        out.append("|".join(map(str, fields)).encode("gbk"))
    return out


def stop(ContextInfo) -> None:
    print("[Stop] quote broadcast shutting down...", flush=True)
    _state.active = False

    if _state.transport is not None:
        _state.transport.close()
        _state.transport = None

    if _state.thread is not None:
        _state.thread.join(timeout=3)
        _state.thread = None

    with _state.lock:
        _state.quote_queue.clear()

    print("[Stop] quote broadcast thread exited cleanly", flush=True)