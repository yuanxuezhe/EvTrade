#!/usr/bin/env python3
"""
ev_ws.py — EvTrade 实时推送订阅

用法:
    python3 ev_ws.py subscribe <stock_code> [--duration 60]
        订阅某只股票 tick 推送, 持续 N 秒 (默认 60s)

    python3 ev_ws.py watch [--stock <code>] [--duration 30] [--order] [--trade] [--asset]
        同时订阅多个频道, 持续 N 秒:
          --order  订阅 ord_cfm (订单状态 push)
          --trade  订阅 trd_cfm (成交回报 push)
          --asset  订阅 asset_update (总资产 push)
          --stock X  订阅 quote_update (指定股票 tick)

    python3 ev_ws.py replay <channel> [--limit 10]
        重连后重放上次订阅 (v21 replay-quote-subscription)

依赖: websockets (pip install websockets)
"""
import argparse
import asyncio
import json
import os
import sys
import urllib.request
import urllib.parse
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))
import ev_login as _login  # noqa: E402

DEFAULT_BASE = os.environ.get("EV_BASE_URL", "http://127.0.0.1:8000")


def _ws_url(channel: str, token: str) -> str:
    base = DEFAULT_BASE.replace("http", "ws", 1).replace("https", "wss", 1)
    return f"{base}/ws/{channel}?token={token}"


async def subscribe_quotes(stock_codes: list, duration: float = 60.0):
    """订阅 quote_update, 持续 N 秒"""
    import websockets
    token = _login.get_token()
    url = _ws_url("quote_update", token)
    print(f"[ev-ws] connecting {url[:60]}...")
    async with websockets.connect(url) as ws:
        # 启动时发 subscribe
        await ws.send(json.dumps({"type": "subscribe", "stock_codes": stock_codes}))
        print(f"[ev-ws] subscribed: {stock_codes}")

        end = time.time() + duration
        count = 0
        try:
            while time.time() < end:
                remaining = end - time.time()
                msg = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 2.0))
                data = json.loads(msg)
                # 过滤心跳
                if data.get("type") == "pong":
                    continue
                if data.get("type") == "subscribe_ack":
                    print(f"[ev-ws] ack: {data}")
                    continue
                if data.get("type") == "quote":
                    count += 1
                    d = data.get("data", {})
                    snap = d.get("snapshot", d)
                    code = snap.get("stock_code", "?")
                    last = snap.get("last_price", 0)
                    bid1 = snap.get("bid1_price", 0)
                    ask1 = snap.get("ask1_price", 0)
                    vol = snap.get("volume", 0)
                    print(f"[{count:>4}] {code} last={last:.3f} bid1={bid1:.3f} ask1={ask1:.3f} vol={vol}")
        except asyncio.TimeoutError:
            pass
        print(f"\n[ev-ws] received {count} ticks in {duration:.0f}s")


async def watch(channels: dict, duration: float = 30.0):
    """watch 模式: 同时订阅多个频道

    channels = {
        "quote_update": ["600519.SH"],   # 订阅标的
        "order_update": None,            # 订阅全部
        "trade_update": None,
        "system_update": None,            # asset_update 在此
    }
    """
    import websockets
    token = _login.get_token()

    tasks = []
    for channel, codes in channels.items():
        url = _ws_url(channel, token)
        tasks.append(_watch_one(channel, url, codes, duration))

    await asyncio.gather(*tasks)


async def _watch_one(channel: str, url: str, codes, duration: float):
    """单 channel 订阅循环"""
    import websockets
    print(f"[ev-ws] {channel} connecting {url[:60]}...")
    try:
        async with websockets.connect(url) as ws:
            if channel == "quote_update" and codes:
                await ws.send(json.dumps({"type": "subscribe", "stock_codes": codes}))
                print(f"[ev-ws] {channel} subscribed: {codes}")

            end = time.time() + duration
            count = 0
            try:
                while time.time() < end:
                    remaining = end - time.time()
                    msg = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 2.0))
                    data = json.loads(msg)
                    t = data.get("type")
                    if t == "pong" or t == "subscribe_ack":
                        continue
                    count += 1
                    # 按 channel 渲染
                    if channel == "quote_update":
                        d = data.get("data", {})
                        snap = d.get("snapshot", d)
                        print(f"[{channel} #{count}] {snap.get('stock_code', '?')} last={snap.get('last_price', 0):.3f}")
                    elif channel == "order_update":
                        d = data.get("data", {})
                        print(f"[{channel} #{count}] {d.get('order_no', '?')} {d.get('stock_code', '?')} status={d.get('status', '?')}")
                    elif channel == "trade_update":
                        d = data.get("data", {})
                        print(f"[{channel} #{count}] {d.get('trade_no', '?')} {d.get('stock_code', '?')} {d.get('price', 0):.3f}x{d.get('volume', 0)}")
                    elif channel == "system_update":
                        d = data.get("data", {})
                        if data.get("type") == "asset_update":
                            print(f"[asset #{count}] cash={d.get('cash', 0):.2f} total={d.get('total_asset', 0):.2f}")
                        else:
                            print(f"[{channel} #{count}] {data.get('type', '?')}")
                    else:
                        print(f"[{channel} #{count}] {json.dumps(data, ensure_ascii=False)[:200]}")
            except asyncio.TimeoutError:
                pass
            print(f"[ev-ws] {channel}: {count} msgs in {duration:.0f}s")
    except Exception as e:
        print(f"[ev-ws] {channel} error: {e}")


# ─────────────── main ───────────────


def main():
    parser = argparse.ArgumentParser(description="ev_ws — EvTrade 实时订阅")
    parser.add_argument("--duration", type=float, default=60.0)
    sub = parser.add_subparsers(dest="cmd", required=True)
    # sub 也接受 --duration
    sub.add_argument = None  # placeholder

    p = sub.add_parser("subscribe", help="订阅股票 tick")
    p.add_argument("--duration", type=float, default=60.0)
    p.add_argument("stock_code", nargs="+", help="可多个: 600519.SH 000001.SZ")
    p.set_defaults(func=lambda a: asyncio.run(subscribe_quotes(a.stock_code, a.duration)))

    p = sub.add_parser("watch", help="同时订阅多个频道")
    p.add_argument("--duration", type=float, default=60.0)
    p.add_argument("--stock", help="订阅此股票 tick (可多个逗号)")
    p.add_argument("--order", action="store_true", help="订阅订单 push")
    p.add_argument("--trade", action="store_true", help="订阅成交 push")
    p.add_argument("--asset", action="store_true", help="订阅资产 push")
    p.set_defaults(func=lambda a: asyncio.run(_cmd_watch(a)))

    args = parser.parse_args()
    args.func(args)


async def _cmd_watch(args):
    channels = {}
    if args.stock:
        channels["quote_update"] = args.stock.split(",")
    if args.order:
        channels["order_update"] = None
    if args.trade:
        channels["trade_update"] = None
    if args.asset:
        channels["system_update"] = None
    if not channels:
        print("[ev-ws] 默认订阅全部频道 (order + trade + asset + quote 600519.SH)")
        channels = {
            "quote_update": ["600519.SH"],
            "order_update": None,
            "trade_update": None,
            "system_update": None,
        }
    await watch(channels, args.duration)


if __name__ == "__main__":
    main()