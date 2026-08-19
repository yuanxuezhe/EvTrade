#!/usr/bin/env python3
"""1 小时压测: 5 只 ETF 全天 tick 密度,统计:
  - sendto 调用次数 (vs 原版理论值)
  - 帧大小分布
  - 帧内 tick 数分布
  - buffer 峰值长度
  - sender 队列长度峰值
  - 内存增量
  - 真 UDP 发包 (默认推到 127.0.0.1:19001, 测试 hqserverd 监听)

模拟 QMT 真实推送节奏:
  - 开盘集合竞价 9:15-9:25: 高频 (每秒每只 ~20 tick)
  - 连续竞价 9:30-11:30 + 13:00-15:00: 中频 (~3 tick/秒/只, 买卖各一笔)
  - 收盘集合竞价 14:57-15:00: 中高频
  - 午休: 0

为压缩 1 小时到测试时间, 设置 time_scale = 60 (60x 快进),即:
  1 分钟真实 = 1 小时模拟
  测试总时长: 1 分钟真实 = 1 个 A 股交易日

**模式切换** (通过 env):
  - USE_REAL_UDP=0 (默认): 用 MetricsSock 计数, 不真发包
  - USE_REAL_UDP=1: 真 sendto 到 UDP_HOST:UDP_PORT (默认 127.0.0.1:19001)
"""
import os
import sys
import time
import threading
import socket
import resource
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "iquant"))

# 加载 quota.py 的 batch 逻辑 (format_quote + _BatchBuffer + sender)
import quota

STOCKS = [
    ("512760.SH", 1.0, 0.003, 500),   # code, base_price, volatility, avg_volume
    ("515650.SH", 2.5, 0.004, 800),
    ("515880.SH", 1.2, 0.002, 600),
    ("560470.SH", 1.5, 0.003, 700),
    ("588710.SH", 2.0, 0.004, 900),
]

USE_REAL_UDP = os.environ.get("USE_REAL_UDP", "0") == "1"
UDP_HOST = os.environ.get("QUOTA_UDP_HOST", "127.0.0.1")
UDP_PORT = int(os.environ.get("QUOTA_UDP_PORT", "19001"))

class MetricsSock:
    """记录 sendto 调用的所有统计。"""
    def __init__(self):
        self.n = 0
        self.bytes_total = 0
        self.bytes_per_frame = []
        self.ticks_per_frame = []
        self.timestamps = []
        self.errors = 0
        self.lock = threading.Lock()

    def setsockopt(self, *a):
        pass

    def sendto(self, data, addr):
        with self.lock:
            self.n += 1
            self.bytes_total += len(data)
            self.bytes_per_frame.append(len(data))
            self.ticks_per_frame.append(data.count(b",") + 1)
            self.timestamps.append(time.monotonic())
        return len(data)


class RealUdpSock(MetricsSock):
    """真 UDP socket, 同时记录 MetricsSock 的所有指标。"""

    def __init__(self, host: str, port: int):
        super().__init__()
        self.host = host
        self.port = port
        self.addr = (host, port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # 加大发送缓冲, 同生产配置
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
        print(f"[RealUdpSock] 真发 UDP -> {host}:{port}", flush=True)

    def sendto(self, data, addr):
        try:
            n = self._sock.sendto(data, self.addr)
        except OSError as e:
            with self.lock:
                self.errors += 1
            return -1
        with self.lock:
            self.n += 1
            self.bytes_total += n
            self.bytes_per_frame.append(n)
            self.ticks_per_frame.append(data.count(b",") + 1)
            self.timestamps.append(time.monotonic())
        return n

    def close(self):
        try:
            self._sock.close()
        except Exception:
            pass


def gen_tick(code, last, high, low, volume, amount, stime):
    """生成 1 条 tick bytes (与 quota.format_quote 一致)。"""
    fields = [
        code, stime,
        f"{last:.4f}", f"{last:.4f}", f"{high:.4f}", f"{low:.4f}", f"{last:.4f}",
        str(volume), f"{amount:.2f}", "0", str(volume // 10),
    ]
    fields += [f"{last + 0.01:.4f}"] * 5  # ask
    fields += [f"{last - 0.01:.4f}"] * 5  # bid
    fields += ["100"] * 10  # askVol + bidVol
    return "|".join(fields).encode("gbk")


def simulate_one_trading_day(time_scale: int = 60, log_interval: int = 10):
    """模拟一个完整 A 股交易日, time_scale 倍速快进。"""
    if USE_REAL_UDP:
        sock = RealUdpSock(UDP_HOST, UDP_PORT)
    else:
        sock = MetricsSock()
    quota._udp_sock = sock
    quota._ensure_sender()

    # 重置 buffer
    quota._buffer._buf.clear()
    quota._buffer._byte_len = 0
    quota._buffer._last_flush_ts = time.monotonic()

    # 5 只 ETF 的实时状态
    state = {}
    for code, base, vol, avg_v in STOCKS:
        state[code] = {
            "last": base, "high": base, "low": base,
            "volume": 0, "amount": 0.0,
        }

    t0_real = time.monotonic()

    # 模拟时间起点: 9:15:00 (开盘集合竞价开始)
    sim_seconds_of_day = 9 * 3600 + 15 * 60
    TRADING_END = 15 * 3600  # 15:00 收盘
    end_sim = TRADING_END

    total_ticks_sent = 0
    last_log_real = t0_real

    TRADING_SECONDS = (TRADING_END - sim_seconds_of_day)

    print(f"[stress] start: 5 stocks, time_scale={time_scale}x, "
          f"sim_duration={TRADING_SECONDS}s real={TRADING_SECONDS/time_scale:.1f}s")
    print(f"[stress] config: batch_max={quota.config.QUOTA_BATCH_MAX} "
          f"flush_ms={quota.config.QUOTA_FLUSH_MS} "
          f"max_bytes={quota.config.QUOTA_MAX_FRAME_BYTES}")

    sim_dt_step = 0.1  # 模拟时间步长 100ms
    real_dt_step = sim_dt_step / time_scale  # 真实 sleep 时长

    while sim_seconds_of_day < end_sim:
        # 判定模拟时间是否在交易时段
        # 9:15-9:30 集合竞价, 9:30-11:30 连续, 13:00-15:00 连续, 14:57-15:00 收盘竞价
        h = int(sim_seconds_of_day // 3600)
        m = (sim_seconds_of_day % 3600) // 60
        sec = sim_seconds_of_day % 60
        in_trading = False
        is_auction = False
        if h == 9 and 15 <= m < 30:
            in_trading = True
            is_auction = True
        elif (h == 9 and m >= 30) or h == 10 or (h == 11 and m < 30):
            in_trading = True
        elif h == 13 or h == 14 or (h == 15 and m == 0 and sec < 1):
            in_trading = True
        if h == 14 and 57 <= m < 60:
            in_trading = True
            is_auction = True

        if in_trading:
            # tick 频率: 集合竞价 20/s/只, 连续竞价 3/s/只
            ticks_per_stock_per_sec = 20 if is_auction else 3
            # 本 step 期望每只股票 ticks_per_stock_per_sec * sim_dt_step 条
            ticks_this_step = ticks_per_stock_per_sec * sim_dt_step
            # 整数化 (用累积小数决定是否触发 tick)
            for code, base, volatility, avg_volume in STOCKS:
                # 每个 step 每只股票发 1 tick (简化, 不做累积小数)
                # 但不能每步都发, 否则太密 → 用 ticks_per_stock_per_sec / 10 (即每100ms 内 tick 数)
                # 这里做简化: 集合竞价每 100ms 2 tick/只, 连续竞价每 100ms 0.3 tick/只
                # 改用固定间隔, 跳到下一只股票
                if not is_auction and (sim_seconds_of_day * 10) % 10 != 0:
                    # 连续竞价: 3 tick/秒 ≈ 每 333ms 一条, 简化: 每秒 5 只轮流
                    tick_now = (int(sim_seconds_of_day * 10) % len(STOCKS)) == STOCKS.index((code, base, volatility, avg_volume))
                else:
                    # 集合竞价: 每只都发
                    tick_now = True

                if not tick_now:
                    continue

                s = state[code]
                import random
                drift = random.uniform(-volatility, volatility) * s["last"]
                s["last"] = max(0.001, s["last"] + drift)
                s["high"] = max(s["high"], s["last"])
                s["low"] = min(s["low"], s["last"])

                vol_inc = random.randint(100, avg_volume * 2)
                s["volume"] += vol_inc
                s["amount"] += s["last"] * vol_inc

                stime = time.strftime("%H%M%S", time.gmtime(sim_seconds_of_day))
                tick = gen_tick(code, s["last"], s["high"], s["low"],
                                s["volume"], s["amount"], stime)
                quota._buffer.enqueue(tick)
                total_ticks_sent += 1

        sim_seconds_of_day += sim_dt_step
        time.sleep(real_dt_step)

        # 定期打印进度 (真实秒)
        if time.monotonic() - last_log_real >= log_interval:
            progress = sim_seconds_of_day / TRADING_SECONDS * 100
            print(f"[stress] sim_t={sim_seconds_of_day/3600:.2f}h ({progress:.0f}%) "
                  f"ticks={total_ticks_sent} frames={sock.n} "
                  f"avg_tpf={total_ticks_sent/max(sock.n,1):.1f} "
                  f"buf_len={len(quota._buffer._buf)} "
                  f"pending={len(quota._pending_frames)}")
            last_log_real = time.monotonic()

    # 收尾
    time.sleep(0.5)
    quota._buffer.flush_now()
    time.sleep(0.3)
    if isinstance(sock, RealUdpSock):
        sock.close()

    return sock, total_ticks_sent


def report(sock: MetricsSock, total_ticks: int, elapsed_real: float):
    """汇总报告。"""
    print("\n" + "=" * 70)
    print("压测报告 — quota.py batch 模式 (5 ETF × 1 交易日)")
    print("=" * 70)

    # 时间
    print(f"\n## 1. 时间")
    print(f"  真实耗时: {elapsed_real:.1f}s")
    print(f"  模拟交易日: 4 小时 (开盘集合 + 连续竞价)")
    print(f"  总 tick 数: {total_ticks}")

    # sendto vs 原版对比
    print(f"\n## 2. sendto 调用 (核心指标)")
    print(f"  实际 sendto 次数: {sock.n}")
    print(f"  原版理论 sendto (每 tick 1 次): {total_ticks}")
    print(f"  压缩比: {sock.n / max(total_ticks, 1) * 100:.2f}%")
    print(f"  节省系统调用: {total_ticks - sock.n} 次 ({100 - sock.n/max(total_ticks,1)*100:.1f}%)")

    # 帧大小分布
    print(f"\n## 3. 帧大小分布")
    if sock.bytes_per_frame:
        sizes = sorted(sock.bytes_per_frame)
        n = len(sizes)
        print(f"  帧数: {n}")
        print(f"  平均: {sum(sizes)/n:.0f} B")
        print(f"  中位: {sizes[n//2]} B")
        print(f"  p95: {sizes[int(n*0.95)]} B")
        print(f"  p99: {sizes[int(n*0.99)]} B")
        print(f"  最大: {max(sizes)} B (UDP 安全上限 8192)")

    # 帧内 tick 数分布
    print(f"\n## 4. 帧内 tick 数分布")
    if sock.ticks_per_frame:
        c = Counter(sock.ticks_per_frame)
        for n_ticks in sorted(c.keys()):
            print(f"  {n_ticks} ticks/帧: {c[n_ticks]} 帧")

    # 字节吞吐
    print(f"\n## 5. 吞吐")
    print(f"  总字节: {sock.bytes_total / 1024:.1f} KB")
    print(f"  平均速率: {sock.bytes_total / elapsed_real / 1024:.1f} KB/s")
    print(f"  平均 tick 速率: {total_ticks / elapsed_real:.0f} ticks/s")

    # 内存
    print(f"\n## 6. 内存")
    usage = resource.getrusage(resource.RUSAGE_SELF)
    print(f"  RSS 峰值: {usage.ru_maxrss / 1024:.1f} MB")

    # 错误
    print(f"\n## 7. 错误")
    print(f"  sendto 错误数: {sock.errors}")
    print(f"  最终 pending 队列残留: {len(quota._pending_frames)}")
    print(f"  最终 buffer 残留: {len(quota._buffer._buf)}")


if __name__ == "__main__":
    # 支持自定义 time_scale: 模拟时间 / 真实时间
    #  time_scale=120 -> 4h A股 = 120s 真实 (2分钟)
    #  time_scale=60  -> 4h A股 = 240s 真实 (4分钟)
    #  time_scale=1   -> 4h A股 = 14400s 真实 (4小时)
    time_scale = int(os.environ.get("TIME_SCALE", "120"))

    t_start = time.monotonic()
    sock, total_ticks = simulate_one_trading_day(time_scale=time_scale)
    elapsed = time.monotonic() - t_start

    report(sock, total_ticks, elapsed)