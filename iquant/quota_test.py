#coding:gbk
"""
==============================================================================
quota_test.py — 159992.SZ 模拟行情 upd 发送 demo

参考 quota.py 的 UDP 推送机制与 32 字段 wire format，不依赖 QMT 行情源，
用程序生成的模拟 tick 持续向 hqserverd 发送行情 upd，用于:
  - hqserverd / 前端 链路联调
  - 验证 32 字段 wire format 解析
  - 行情推送演示 / 简单压测

Wire format 与 quota.py 完全一致（复用 quota.format_quote，保证字节级兼容）:
  code|stime|last|open|high|low|lastClose|volume|amount|openInt|txnNum|
  ask1..ask5|bid1..bid5|askVol1..askVol5|bidVol1..bidVol5

用法:
  python quota_test.py [--ticks N] [--interval MS] [--host H] [--port P] [--seed S]
  例:
  python quota_test.py --ticks 200 --interval 50
  python quota_test.py --ticks 0 --interval 200   # 无限发送，直到 Ctrl+C
==============================================================================
"""
import argparse
import datetime
import random
import socket
import time

# 复用 quota.py 的公开入口：wire format 格式化 + UDP 目标配置（不重复实现）
from quota import config as quota_config, format_quote

# 目标标的（与 quota_his_test 一致）
STOCK_CODE = "159992.SZ"
DEFAULT_LAST_CLOSE = 1.234  # 模拟昨收价（ETF 约 1.x 元）


class QuoteSimulator:
    """生成 159992.SZ 的模拟 tick，dict 结构同 QMT on_quote 的 datas 入参。

    价格随机游走，同时维护 open/high/low/volume/amount，
    并围绕最新价生成 5 档买卖盘。
    """

    def __init__(self, code=STOCK_CODE, last_close=DEFAULT_LAST_CLOSE, seed=None):
        self.code = code
        self.last_close = last_close
        self.last = last_close
        self.open = last_close
        self.high = last_close
        self.low = last_close
        self.volume = 0
        self.amount = 0.0
        self.txn_num = 0
        self.rng = random.Random(seed)

    def next(self, stime):
        """产生下一个 tick 的 datas 字典（key=股票代码，value=行情字段）。"""
        # 随机游走一步（相对幅度在 ±0.4% 内）
        self.last += self.rng.uniform(-0.004, 0.004) * self.last
        self.last = max(self.open * 0.9, self.last)   # 防止跌穿下限
        self.high = max(self.high, self.last)
        self.low = min(self.low, self.last)

        vol_inc = self.rng.randint(100, 5000)
        self.volume += vol_inc
        self.amount += self.last * vol_inc
        self.txn_num += self.rng.randint(1, 20)

        spread = self.last * 0.0005  # 0.05% 档差
        ask_price = [self.last + spread * (i + 1) for i in range(5)]
        bid_price = [max(0.0001, self.last - spread * (i + 1)) for i in range(5)]
        ask_vol = [self.rng.randint(100, 5000) for _ in range(5)]
        bid_vol = [self.rng.randint(100, 5000) for _ in range(5)]

        return {
            self.code: {
                "stime": stime,
                "lastPrice": self.last,
                "open": self.open,
                "high": self.high,
                "low": self.low,
                "lastClose": self.last_close,
                "volume": self.volume,
                "amount": self.amount,
                "openInt": 0,          # ETF 无持仓量
                "transactionNum": self.txn_num,
                "askPrice": ask_price,
                "bidPrice": bid_price,
                "askVol": ask_vol,
                "bidVol": bid_vol,
            }
        }


def run(ticks, interval_ms, host, port, seed):
    sim = QuoteSimulator(seed=seed)
    addr = (host, port)

    print("=" * 70)
    print("quota_test: 模拟行情 upd -> %s:%s  标的=%s  ticks=%s  interval=%sms"
          % (host, port, STOCK_CODE, "INF" if ticks == 0 else ticks, interval_ms))
    # 打印首条 wire format（gbk 解码展示），便于核对 32 字段
    sample = format_quote(QuoteSimulator(seed=seed).next("00000000000000"))[0]
    print("[wire] " + sample.decode("gbk"))
    print("=" * 70)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    count = 0
    try:
        while ticks == 0 or count < ticks:
            stime = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            datas = sim.next(stime)
            # format_quote 复用 quota.py 的 wire format（gbk 编码，一 tick 一 datagram）
            for line in format_quote(datas):
                sock.sendto(line, addr)
            count += 1

            if count == 1 or count % 10 == 0:
                print("[tick %6d] %s last=%.4f high=%.4f low=%.4f vol=%d"
                      % (count, stime, sim.last, sim.high, sim.low, sim.volume),
                      flush=True)

            time.sleep(interval_ms / 1000.0)
    except KeyboardInterrupt:
        print("\n[quota_test] KeyboardInterrupt, stop sending.")
    finally:
        sock.close()

    print("[quota_test] done. sent %d ticks." % count)


def parse_args():
    p = argparse.ArgumentParser(description="159992.SZ 模拟行情 upd UDP 发送 demo")
    p.add_argument("--ticks", type=int, default=100,
                   help="发送 tick 数，0=无限（直到 Ctrl+C），默认 100")
    p.add_argument("--interval", type=float, default=50,
                   help="tick 间隔（毫秒），默认 50ms")
    p.add_argument("--host", default=quota_config.UDP_HOST,
                   help="目标 hqserverd 地址，默认 %s" % quota_config.UDP_HOST)
    p.add_argument("--port", type=int, default=quota_config.UDP_PORT,
                   help="目标端口，默认 %d" % quota_config.UDP_PORT)
    p.add_argument("--seed", type=int, default=None,
                   help="随机种子，固定后行情可复现")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(args.ticks, args.interval, args.host, args.port, args.seed)
