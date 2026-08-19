#!/usr/bin/env python3
"""2026-08-19 quota.py batch 模式单元测试

覆盖 _BatchBuffer 三阈值 + sendto 行为 + 向后兼容:
  - 阈值 1: tick 数 >= QUOTA_BATCH_MAX (50)
  - 阈值 2: 帧字节数 > QUOTA_MAX_FRAME_BYTES (4096)
  - 阈值 3: 自上次 flush 起 QUOTA_FLUSH_MS (200ms)
  - 单 tick / 多 tick 解码兼容性
  - 字段缺失不阻塞

注: 测试中通过 monkeypatch 替换 _udp_sock, 避免真实 UDP 发送。
    测试间共享 _buffer 单例, 因此在 setUp 中清空 deque。
"""
import sys
import time
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "iquant"))

import quota


class FakeSock:
    """最小 UDP socket mock, 记录每次 sendto 的字节数和时间戳。"""

    def __init__(self):
        self.frames = []
        self.n = 0
        self.lock = threading.Lock()

    def setsockopt(self, *a, **kw):
        pass

    def sendto(self, data, addr):
        with self.lock:
            self.frames.append((time.monotonic(), len(data), data))
            self.n += 1
        return len(data)


def _reset_buffer():
    """清空 buffer 全局状态, 但保留 timer 线程已退 (下次 enqueue 重启)。"""
    quota._buffer._buf.clear()
    quota._buffer._byte_len = 0
    quota._buffer._last_flush_ts = time.monotonic()


def _make_tick(code: str = "600519.SH", last: float = 100.5) -> bytes:
    """构造一个最小可用的 tick 字符串 (与 quota.format_quote 一致: 31 字段 = 30 个 '|')。

    字段顺序:
      0:code 1:stime 2:last 3:open 4:high 5:low 6:lastClose
      7:volume 8:amount 9:openInt 10:txnNum
      11-15: askPrice 1-5
      16-20: bidPrice 1-5
      21-25: askVol 1-5
      26-30: bidVol 1-5
    """
    fields = [
        code, "093000",
        f"{last:.4f}", "100", "101", "99", "99.5",
        "1000", "100500", "0", "10",
    ] + ["1.0"] * 5 + ["1.0"] * 5 + ["100"] * 5 + ["100"] * 5
    assert len(fields) == 31, f"字段数必须 =31, 实际 {len(fields)}"
    return "|".join(fields).encode("gbk")


@pytest.fixture(autouse=True)
def fake_sock(monkeypatch):
    """每个 case 自动注入 FakeSock + 重置 buffer。

    sender 线程只起一次 (module 级), 不要在每个 case 重置 _sender_started,
    否则会启多个 sender 线程抢同一队列, 导致数据丢失。
    """
    sock = FakeSock()
    monkeypatch.setattr(quota, "_udp_sock", sock)
    _reset_buffer()
    yield sock
    _reset_buffer()


def _module_setup_once():
    """module 级 setup: 确保 sender 只起一次。"""
    if not quota._sender_started:
        quota._ensure_sender()


_module_setup_once()


def _wait_drain(sock: FakeSock, expected_min_frames: int, timeout: float = 1.0):
    """等待 sender 线程把 _pending_frames 全部 sendto 出去。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if sock.n >= expected_min_frames:
            # 再给 sender 一点时间清空队列
            time.sleep(0.05)
            return True
        time.sleep(0.01)
    return False


# ================================================================
# 阈值 1: tick 数触发
# ================================================================
class TestBatchSizeThreshold:
    """累积 50 条 tick 必须立即 flush。"""

    def test_size_threshold_50(self, fake_sock):
        for i in range(50):
            quota._buffer.enqueue(_make_tick(f"{(i % 100):06d}.SH"))
        assert _wait_drain(fake_sock, 1, timeout=0.5)
        # 50 条应该正好 1 帧
        assert fake_sock.n == 1, f"期望 1 帧, 实际 {fake_sock.n}"
        # 帧里包含 50 条 tick, 用 ',' 数 = 49
        frame = fake_sock.frames[0][2]
        assert frame.count(b",") == 49, f"帧内 50 条应有 49 个 ',', 实际 {frame.count(b',')}"
        # 单 tick ~140B (gbk), 50 条 ~7KB, 应在 8KB 阈值内 (走 size 阈值)
        assert fake_sock.frames[0][1] < 8192, f"单帧应 <8KB, 实际 {fake_sock.frames[0][1]}"

    def test_size_below_threshold_waits_timer(self, fake_sock):
        """49 条 < 50 条, 必须等定时器 flush (200ms)。"""
        for i in range(49):
            quota._buffer.enqueue(_make_tick(f"{(i % 100):06d}.SH"))
        # 立即检查: 应该还没有 sendto
        time.sleep(0.05)
        assert fake_sock.n == 0, f"49 条未达阈值不应立即 flush, 实际 {fake_sock.n}"
        # 等定时器
        assert _wait_drain(fake_sock, 1, timeout=0.5)
        assert fake_sock.n == 1


# ================================================================
# 阈值 2: 帧字节数触发
# ================================================================
class TestBatchBytesThreshold:
    """累积字节数 > 8KB 必须立即 flush (即使 tick 数 < 50)。"""

    def test_bytes_threshold_with_few_large_ticks(self, fake_sock):
        """构造大 tick: 每条约 400B, 22 条 = 8800B > 8192 应立即 flush。"""
        # 11 个长字段, 每字段 ~40 字符, 总长约 440B
        big_tick = ("X" * 9 + ".SH") + "|" + ("1" * 35) + "|" + ("1" * 35) + "|" + ("1" * 35) + "|" + ("1" * 35) + "|" + ("1" * 35)
        for _ in range(22):
            quota._buffer.enqueue(big_tick.encode())
        assert _wait_drain(fake_sock, 1, timeout=0.5)
        assert fake_sock.n >= 1, "字节数 > 8KB 应立即 flush"


# ================================================================
# 阈值 3: 定时器触发
# ================================================================
class TestBatchTimerThreshold:
    """200ms 内必须 flush。"""

    def test_timer_flush_slow_market(self, fake_sock):
        quota._buffer.enqueue(_make_tick("600001.SH"))
        time.sleep(0.05)
        assert fake_sock.n == 0
        # 200ms 后定时器必须 flush
        assert _wait_drain(fake_sock, 1, timeout=0.5)
        assert fake_sock.n == 1

    def test_timer_quiet_then_burst(self, fake_sock):
        """慢市: 先 1 条, 等 200ms 后再来 60 条。"""
        quota._buffer.enqueue(_make_tick("600001.SH"))
        # 等 timer 200ms flush + sender sendto, 留 100ms 缓冲
        assert _wait_drain(fake_sock, 1, timeout=0.5)
        assert fake_sock.n == 1, f"慢市 1 条应在 200ms 内 flush, 实际 {fake_sock.n} 次"
        for i in range(60):
            quota._buffer.enqueue(_make_tick(f"{(i % 100):06d}.SH"))
        assert _wait_drain(fake_sock, 2, timeout=0.5)
        # 第 1 帧: 1 条; 第 2 帧: 60 条 (50+10)
        assert fake_sock.n == 2


# ================================================================
# 多线程 + 锁正确性
# ================================================================
class TestConcurrency:
    """多线程并发 enqueue 不能丢数据, 也不能 deadlock。"""

    def test_concurrent_enqueue_no_loss(self, fake_sock):
        N_THREADS = 4
        N_PER_THREAD = 200
        threads = []

        def worker(start):
            for i in range(start, start + N_PER_THREAD):
                quota._buffer.enqueue(_make_tick(f"{(i % 100):06d}.SH"))

        for t in range(N_THREADS):
            threads.append(threading.Thread(target=worker, args=(t * N_PER_THREAD,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        # 等所有帧发出
        time.sleep(0.5)
        total_ticks_in_frames = sum(f[2].count(b",") + 1 for f in fake_sock.frames)
        expected = N_THREADS * N_PER_THREAD
        assert total_ticks_in_frames == expected, (
            f"tick 丢失: 帧内合计 {total_ticks_in_frames}, 期望 {expected}"
        )


# ================================================================
# 协议向后兼容 (Rust 端验证用)
# ================================================================
class TestWireFormatCompat:
    """帧内 ',' 分隔 N 条 tick, Rust 端 split(',') 必须正确解析。"""

    def test_single_tick_no_comma(self):
        """单 tick 无逗号: split(',') 应得 1 个 tick (向后兼容原版)。"""
        tick = _make_tick("600519.SH")
        parts = tick.decode("gbk").split(",")
        assert len(parts) == 1

    def test_batch_split(self):
        """多 tick 帧: split(',') 应得 N 个 tick。"""
        ticks = [_make_tick(f"{(i % 100):06d}.SH") for i in range(10)]
        frame = b",".join(ticks)
        parts = frame.decode("gbk").split(",")
        assert len(parts) == 10
        # 每个 part 内部 '|' 分字段 (32 字段 = 31 个 '|')
        for p in parts:
            assert p.count("|") == 30, f"单 tick 应有 30 个 '|', 实际 {p.count('|')}"

    def test_empty_tick_in_batch_dropped(self):
        """连续 ',' 或尾随 ',' 产生空字符串, Rust 端应跳过。"""
        frame = _make_tick("600519.SH") + b"," + b"," + _make_tick("600001.SH")
        parts = frame.decode("gbk").split(",")
        # parts = ["600519.SH|...", "", "600001.SH|..."]
        non_empty = [p for p in parts if p.strip()]
        assert len(non_empty) == 2


# ================================================================
# 配置层
# ================================================================
class TestConfig:
    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("QUOTA_BATCH_MAX", "10")
        monkeypatch.setenv("QUOTA_FLUSH_MS", "100")
        monkeypatch.setenv("QUOTA_MAX_FRAME_BYTES", "1024")
        # 重读 Config (重新执行类体)
        import importlib
        importlib.reload(quota)
        assert quota.config.QUOTA_BATCH_MAX == 10
        assert quota.config.QUOTA_FLUSH_MS == 100
        assert quota.config.QUOTA_MAX_FRAME_BYTES == 1024