#!/usr/bin/env python3
"""
EvTrade 行情订阅 Demo —— 外部系统接入示例

功能：
  1) JWT 登录拿到 token
  2) REST 一次性拉最新快照（可跳过,直接 WS 也可）
  3) WS 长连接到 /ws/quote_update,订阅若干股票
  4) 实时接收 quote_update 推送
  5) 心跳 + 自动重连
  6) 优雅退出（unsubscribe + close）

📌 业务背景：
  EvTrade backend 通过 hqserver 收 XtQuant 行情,落地本地 QuoteCache + 每 60s
  批量 UPSERT 到 MySQL quote_snapshots 表。外部应用只要拿到 JWT,就能通过
  这套 subscribe 协议订阅任意股票（限购 200/stock_code/connection）。

📌 用法：
  pip install websockets requests
  python external_quote_subscriber.py
"""
from __future__ import annotations
import asyncio
import json
import logging
import sys
import time
from typing import List

import requests
import websockets

# ──────────────────── 配置 ────────────────────
BASE_URL = "http://127.0.0.1:8000"        # 直连后端调试
# BASE_URL = "https://evtrade.ngx.evdata.top:50443"   # 经 Nginx 反代的公网地址

USERNAME = "admin"
PASSWORD = "admin123"

WATCH_CODES = ["513800.SH", "510300.SH", "600519.SH"]   # 想要订阅的股票
PING_INTERVAL = 25                                       # 比 server 30s 略短
RECONNECT_BACKOFF = 3                                    # 重连间隔(s)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("quote_demo")


# ──────────────────── Step 1: 拿 JWT ────────────────────
def login() -> str:
    """
    POST /api/auth/login 拿 access_token。

    协议:application/x-www-form-urlencoded + OAuth2PasswordRequestForm
    不接受 JSON body！username/password 是 form 字段。
    """
    url = f"{BASE_URL}/api/auth/login"
    resp = requests.post(
        url,
        data={"username": USERNAME, "password": PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=5,
    )
    resp.raise_for_status()
    data = resp.json()
    log.info("✅ 登录成功,user=%s role=%s", data["user"]["username"], data["user"]["role"])
    return data["access_token"]


# ──────────────────── Step 2 (可选): REST 一次性拉最新快照 ────────────────────
def fetch_snapshots_once(token: str, codes: List[str]) -> dict:
    """
    POST /api/quote/snapshots 一次返所有请求股票的最新一条快照。

    📌 适用场景：UI 首屏加载, 避免 ws 还没 tick 时空白
    📌 注意 body 是 dict 不是 list —— {stock_codes: [...]}
    """
    url = f"{BASE_URL}/api/quote/snapshots"
    resp = requests.post(
        url,
        json={"stock_codes": codes},
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["snapshots"]   # { "513800.SH": {22 字段}, ... }


# ──────────────────── Step 3: WS 订阅长连接 ────────────────────
async def run_subscriber(token: str, codes: List[str], max_seconds: int = 15):
    """
    流程:
      connect → receive hello (or first push) → 发送 subscribe
      → 收到 subscribe_ack(包含按订阅股票的最后一帧快照)
      → 进入 recv 循环, 收 quote_update / 服务端 ping
      → 每 PING_INTERVALs 主动 send ping 保活
      → max_seconds 到或 Ctrl+C 时发 unsubscribe + close

    📌 重要协议:
    - 入站 ws message = {type: ..., data...} 全部 JSON
    - 出站:            {type: 'subscribe', stock_codes: [...]} | 'unsubscribe' | 'ping'
    - 入站:            {type: 'subscribe_ack', stock_codes, snapshots}
                       {type: 'unsubscribe_ack', stock_codes}
                       {type: 'quote_update', data: {stock_code, last_price, ...}}
                       {type: 'pong', ts}
    """
    # ws URL：HTTP→ws, HTTPS→wss; /ws/quote_update 是行情频道
    ws_base = BASE_URL.replace("https://", "wss://").replace("http://", "ws://")
    url = f"{ws_base}/ws/quote_update?token={token}"

    log.info("🛰  准备连接 %s", url.split("?")[0] + "?token=***")
    async with websockets.connect(url, ping_interval=None) as ws:    # 自己处理 ping
        log.info("🟢 WS 已建立")

        # 3.1 发送 subscribe（订阅多支股票可以一批发,后端会立即返回最后一帧）
        await ws.send(json.dumps({"type": "subscribe", "stock_codes": codes}))
        log.info("📨 已发送 subscribe: %s", codes)

        # 3.2 进入 recv loop
        t0 = time.time()
        last_ping = time.time()
        quote_count = 0
        try:
            while time.time() - t0 < max_seconds:
                # 计算 timeout：取"距离 max_seconds 还剩"和"距离下次必发 ping 还剩"的较小值
                recv_timeout = min(max_seconds - (time.time() - t0), PING_INTERVAL)
                if recv_timeout <= 0:
                    break

                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=recv_timeout)
                except asyncio.TimeoutError:
                    # 到了主动 ping 的时间
                    await ws.send(json.dumps({"type": "ping"}))
                    last_ping = time.time()
                    log.debug("💗 sent ping")
                    continue

                msg = json.loads(raw)
                mtype = msg.get("type")

                if mtype == "subscribe_ack":
                    snaps = msg.get("snapshots", {}) or {}
                    log.info("✅ subscribe_ack: %d/%d 个 code 有最新快照", len(snaps), len(codes))
                    for code, snap in snaps.items():
                        log.info("   %s: last_price=%s open=%s high=%s low=%s",
                                 code, snap.get("last_price"), snap.get("open_price"),
                                 snap.get("high_price"), snap.get("low_price"))

                elif mtype == "unsubscribe_ack":
                    log.info("✅ unsubscribe_ack: %s", msg.get("stock_codes"))

                elif mtype == "quote_update":
                    data = msg.get("data", {})
                    code = data.get("stock_code", "?")
                    price = data.get("last_price")
                    quote_count += 1
                    # 高频演示：不要每条都 log,按时间窗口聚合
                    if quote_count % 20 == 1:
                        log.info("📈 quote_update[%d]: %s last=%.3f vol=%s",
                                 quote_count, code, price, data.get("volume"))

                elif mtype == "pong":
                    log.debug("💗 pong")

                elif mtype == "ping":
                    # 服务端主动 ping，回应 pong（这里依赖 http 后端似乎没有显式要求，
                    # 因为服务端 endpoint 注释里说"收 ping 就返 pong"，所以双向对称即可）
                    await ws.send(json.dumps({"type": "pong"}))
                    log.debug("💗 resp pong")

                else:
                    log.warning("⚠️ 未知消息 type=%s", mtype)

                # 周期性主动 ping
                if time.time() - last_ping >= PING_INTERVAL:
                    await ws.send(json.dumps({"type": "ping"}))
                    last_ping = time.time()
                    log.debug("💗 sent ping (loop end)")

        except KeyboardInterrupt:
            log.info("⏹ Ctrl+C,准备退出")
        finally:
            # 取消订阅 + 优雅关闭
            try:
                await ws.send(json.dumps({"type": "unsubscribe", "stock_codes": codes}))
                log.info("📤 unsubscribe 已发送")
                # 给服务端一点时间回 ack
                try:
                    await asyncio.wait_for(ws.recv(), timeout=2)
                except asyncio.TimeoutError:
                    pass
            except Exception as e:
                log.warning("unsubscribe 异常:%s", e)

    log.info("🔚 done. 共收 %d 条 quote_update", quote_count)


# ──────────────────── 入口 ────────────────────
async def main():
    token = login()

    # Step 2 (可选)：REST 一次性拉
    log.info("── Step 2: 一次性 REST 拉快照 ──")
    snaps = fetch_snapshots_once(token, WATCH_CODES)
    if snaps:
        for code, s in list(snaps.items())[:2]:
            log.info("REST snap %s: %s", code, s.get("last_price"))
    else:
        log.info("(cache miss 全部,服务冷启动期正常)")

    # Step 3：WS 订阅推送
    log.info("── Step 3: WS 订阅,持续 60s ──")
    await run_subscriber(token, WATCH_CODES, max_seconds=15)

    log.info("👋 all done,退出")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        log.exception("FATAL: %s", e)
        sys.exit(1)
