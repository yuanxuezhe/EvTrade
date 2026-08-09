"""
ws_ping_pong_probe.py — 直接探测 ws ping/pong 协议

目的: 验证服务端 ws/endpoint.py 是否真的回 pong, 不依赖前端 ws_heartbeat.

用法:
  python tests/server/tools/ws_ping_pong_probe.py

逻辑:
  1. 注册一个临时 token 到 session cache
  2. 连 ws://localhost:8000/ws/quote_update?token=...
  3. 每 30s 发一次 ping
  4. 统计 90s 内收到多少 pong
  5. 打印结论
"""
import asyncio
import json
import sys
import time

import websockets

# Windows GBK 控制台无法编码 ✅/❌ emoji → 强制 UTF-8 stdout (探测结论打印处)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


async def probe(host: str = 'localhost:8000', duration_sec: int = 95):
    """探测 ping/pong"""
    # 1. 准备一个合法 token (绕过鉴权)
    sys.path.insert(0, 'server')
    from auth.security import create_access_token
    from auth import session
    token = create_access_token({'sub': '1', 'role': 'trader'})
    session.register_token(token, user_id=1, role='trader')

    url = f'ws://{host}/ws/quote_update?token={token}'
    print(f'[probe] connecting to {url}')

    sent_pings = []
    received_pongs = []
    received_other = []

    async with websockets.connect(url) as ws:
        print(f'[probe] connected')
        start = time.time()

        # 先发个 subscribe 测试 onmessage
        await ws.send(json.dumps({'type': 'subscribe', 'stock_codes': ['000001.SZ']}))
        print(f'[probe] sent subscribe, waiting for ack...')

        # 主循环: 每 30s 发 ping
        next_ping_at = time.time() + 5  # 第 5s 发第一个 ping, 模拟客户端
        while time.time() - start < duration_sec:
            now = time.time()
            if now >= next_ping_at:
                ts = int(time.time() * 1000)
                await ws.send(json.dumps({'type': 'ping', 'ts': ts}))
                sent_pings.append(ts)
                print(f'[probe] sent ping #{len(sent_pings)} (ts={ts})')
                next_ping_at = now + 30  # 每 30s 一次

            # 收消息, 超时 100ms 让出循环
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.1)
                payload = json.loads(raw)
                ptype = payload.get('type')
                if ptype == 'pong':
                    received_pongs.append(payload.get('ts'))
                    print(f'[probe] received pong (ts={payload.get("ts")}, lag={int(time.time()*1000) - payload.get("ts", 0)}ms)')
                elif ptype == 'subscribe_ack':
                    print(f'[probe] received subscribe_ack (snapshots={len(payload.get("snapshots", {}))})')
                else:
                    received_other.append(ptype)
            except asyncio.TimeoutError:
                pass
            except websockets.ConnectionClosed as e:
                print(f'[probe] connection closed: code={e.code}, reason={e.reason}')
                break

    elapsed = time.time() - start
    print()
    print('=' * 60)
    print(f'[probe] RESULT')
    print(f'[probe] elapsed: {elapsed:.1f}s')
    print(f'[probe] sent pings: {len(sent_pings)}')
    print(f'[probe] received pongs: {len(received_pongs)}')
    print(f'[probe] received other (业务消息): {received_other[:5]}...')

    if len(received_pongs) == len(sent_pings):
        print(f'[probe] ✅ PASS: 服务端 pong 与 ping 一一对应, ping/pong 协议正常')
    elif len(received_pongs) == 0:
        print(f'[probe] ❌ FAIL: 服务端完全没回 pong, ping/pong 协议失灵')
    else:
        print(f'[probe] ⚠️ PARTIAL: {len(received_pongs)}/{len(sent_pings)} pong 回来, 服务端 pong 不稳定')


if __name__ == '__main__':
    host = sys.argv[1] if len(sys.argv) > 1 else 'localhost:8000'
    duration = int(sys.argv[2]) if len(sys.argv) > 2 else 95
    asyncio.run(probe(host, duration))