#!/usr/bin/env python3
"""
quota_subscriber_demo.py — 外部系统接入 EvTrade 行情订阅完整示例

📌 流程：
  1) 用 quota / quota 账号登录拿到 JWT
  2) (可选) REST 一次性拉最新快照首屏不空白
  3) WS 长连到 /ws/quote_update，订阅股票码
  4) 持续接收 quote_update 增量推送 30s
  5) 优雅退出 (unsubscribe + close)

📌 依赖：pip install websockets requests
📌 直接跑：python quota_subscriber_demo.py
"""
from __future__ import annotations
import asyncio, json, sys, time
import requests, websockets

# ────────────── 配置 ──────────────
BASE_URL  = "http://127.0.0.1:8000"   # 直连后端调试
# BASE_URL  = "https://evtrade.ngx.evdata.top:50443"   # 公网反代

USERNAME  = "quota"
PASSWORD  = "quota"

WATCH_CODES  = ["513800.SH", "510300.SH", "600519.SH"]
RUN_SECONDS  = 12    # demo 持续时间
PING_GAP     = 25    # 比服务端 30s 略短


def login() -> str:
    """OAuth2PasswordRequestForm 要求 x-www-form-urlencoded，不是 JSON。"""
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        data={"username": USERNAME, "password": PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=5,
    )
    r.raise_for_status()
    token = r.json()["access_token"]
    print(f"✅ 登录成功 token={token[:25]}...")
    return token


def fetch_snapshots(token: str, codes: list) -> dict:
    """一次性拉所有请求 code 的最新快照 — UI 首屏不空白."""
    r = requests.post(
        f"{BASE_URL}/api/quote/snapshots",
        json={"stock_codes": codes},         # 注意 body 是 dict 不是 list
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["snapshots"]


async def ws_subscribe_and_listen(token: str, codes: list, seconds: int):
    """WS 长连：subscribe → 收 subscribe_ack → 收 quote_update → 退出 unsubscribe."""
    ws_base = BASE_URL.replace("https://", "wss://").replace("http://", "ws://")
    url     = f"{ws_base}/ws/quote_update?token={token}"

    print(f"🛰  连接 {url.split('?')[0]}?token=***")
    async with websockets.connect(url, ping_interval=None) as ws:
        # 1. 发送 subscribe，后端会立即返 subscribe_ack 含当前最后一帧
        await ws.send(json.dumps({"type": "subscribe", "stock_codes": codes}))
        print(f"📨 已发送 subscribe: {codes}")

        # 2. 进入 recv 循环
        t0          = time.time()
        last_ping   = time.time()
        n_updates   = 0
        n_acks      = 0

        try:
            while time.time() - t0 < seconds:
                # 计算"还能等多久 = 该收 next message"
                remaining  = seconds - (time.time() - t0)
                recv_limit = min(remaining, PING_GAP)
                if recv_limit <= 0:
                    break

                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=recv_limit)
                except asyncio.TimeoutError:
                    # 主动 ping
                    await ws.send(json.dumps({"type": "ping"}))
                    last_ping = time.time()
                    continue

                msg = json.loads(raw)
                t   = msg.get("type")

                if   t == "subscribe_ack":
                    snaps = msg.get("snapshots", {}) or {}
                    n_acks += 1
                    print(f"\n✅ subscribe_ack: {len(snaps)}/{len(codes)} 个 code 有最新快照")
                    for code, s in snaps.items():
                        print(f"   📊 {code:>10} | last={s.get('last_price')} vol={s.get('volume')}")

                elif t == "quote":
                    # 服务端真实推送格式：{type:"quote", channel:"quote_update", data:{...}}
                    data   = msg.get("data", {})
                    code   = data.get("stock_code", "?")
                    price  = data.get("last_price")
                    n_updates += 1
                    # 推送高频，只打印前 10 + 每 50 条
                    if n_updates <= 10 or n_updates % 50 == 0:
                        print(f"📈 tick #{n_updates:>4} | {code:>10} | last={price}")

                elif t == "quote_update":
                    # 兼容旧 spec（demo 文件展示兼容两种命名）
                    data   = msg.get("data", {})
                    code   = data.get("stock_code", "?")
                    price  = data.get("last_price")
                    n_updates += 1
                    if n_updates <= 10 or n_updates % 50 == 0:
                        print(f"📈 tick #{n_updates:>4} | {code:>10} | last={price}")

                elif t == "unsubscribe_ack":
                    print("✅ unsubscribe_ack OK")

                elif t == "pong":
                    pass  # 服务端 ping 回复，无需动作

                elif t == "ping":
                    # 服务端发 ping，回 pong
                    await ws.send(json.dumps({"type": "pong"}))

                else:
                    print(f"⚠  未知消息 type={t}: {msg}")

                # 周期主动 ping 保活
                if time.time() - last_ping >= PING_GAP:
                    await ws.send(json.dumps({"type": "ping"}))
                    last_ping = time.time()

        except KeyboardInterrupt:
            print("\n⏹  Ctrl+C")
        finally:
            # 优雅退出
            try:
                await ws.send(json.dumps({"type": "unsubscribe", "stock_codes": codes}))
                print("📤 unsubscribe 已发送")
                # 给服务端 2s 回 ack
                try:
                    await asyncio.wait_for(ws.recv(), timeout=2)
                except asyncio.TimeoutError:
                    pass
            except Exception as e:
                print(f"⚠  unsubscribe err: {e}")

        elapsed = time.time() - t0
        print(f"\n🔚 done: 持续 {elapsed:.1f}s, 共收 {n_updates} 条 quote_update, {n_acks} 条 subscribe_ack")


async def main():
    print("━" * 50)
    print("  EvTrade 行情订阅 Demo — 用户 quota/quota")
    print("━" * 50)

    token = login()

    print("\n── (1) REST 一次性拉快照 ──")
    try:
        snaps = fetch_snapshots(token, WATCH_CODES)
        if snaps:
            for code in list(snaps.keys())[:3]:
                s = snaps[code]
                print(f"   REST {code}: last={s.get('last_price')} vol={s.get('volume')}")
        else:
            print("   (空 — cache 冷启动中)")
    except Exception as e:
        print(f"   ⚠ REST 失败: {e}")

    print(f"\n── (2) WS subscribe + 实时接收 {RUN_SECONDS}s ──")
    await ws_subscribe_and_listen(token, WATCH_CODES, RUN_SECONDS)

    print("\n👋 demo 结束\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"FATAL: {e}")
        sys.exit(1)
