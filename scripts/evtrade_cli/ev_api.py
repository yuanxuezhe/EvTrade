#!/usr/bin/env python3
"""
ev_api.py — EvTrade 交易 HTTP API 封装

用法:
    python3 ev_api.py buy <stock_code> <volume> <price> [--type limit]
    python3 ev_api.py sell <stock_code> <volume> <price>
    python3 ev_api.py cancel <order_no>
    python3 ev_api.py asset
    python3 ev_api.py positions
    python3 ev_api.py orders [--status pending|filled|cancelled|partial]
    python3 ev_api.py trades [--date YYYYMMDD]
    python3 ev_api.py stock <stock_code>     # 查股票基本信息

通用选项:
    --json    输出 JSON 格式
    --base URL  默认 $EV_BASE_URL 或 http://127.0.0.1:8000

示例:
    python3 ev_api.py buy 600519.SH 100 1820.5
    python3 ev_api.py asset --json
    python3 ev_api.py orders --status pending
"""
import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

# 复用 ev_login 的 token 缓存
SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))
import ev_login as _login  # noqa: E402

DEFAULT_BASE = os.environ.get("EV_BASE_URL", "http://127.0.0.1:8000")


def _http(method: str, path: str, token: str, body=None, timeout: float = 10.0) -> dict:
    url = f"{_login.DEFAULT_BASE if _login.DEFAULT_BASE else DEFAULT_BASE}{path}"
    headers = {"Authorization": f"Bearer {token}"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        raise SystemExit(f"[ev] {method} {path} → HTTP {e.code}: {body}")
    except Exception as e:
        raise SystemExit(f"[ev] {method} {path} → {e}")


def _print_table(rows: list, columns: list) -> None:
    """人类可读表格输出"""
    if not rows:
        print("(无数据)")
        return
    # 计算列宽
    widths = {col: len(col) for col in columns}
    for row in rows:
        for col in columns:
            v = str(row.get(col, ""))
            widths[col] = max(widths[col], min(len(v), 30))
    # 表头
    print("  ".join(col.ljust(widths[col]) for col in columns))
    print("  ".join("-" * widths[col] for col in columns))
    # 数据行
    for row in rows:
        print("  ".join(str(row.get(col, "")).ljust(widths[col])[:30] for col in columns))


# ─────────────── 子命令 ───────────────


def cmd_buy(args):
    return _cmd_order(args, side="BUY")


def cmd_sell(args):
    return _cmd_order(args, side="SELL")


def _cmd_order(args, side: str):
    """下单: buy/sell 共用"""
    token = _login.get_token()
    # 23=买 24=卖 (xtquant 柜台约定)
    order_type = "23" if side == "BUY" else "24"
    # 44=限价 45=市价 等 (FIX_PRICE=44)
    price_type = 44 if args.type == "limit" else 45
    body = {
        "stock_code": args.stock_code,
        "price": float(args.price),
        "volume": int(args.volume),
        "order_type": order_type,
        "price_type": price_type,
    }
    result = _http("POST", "/api/orders/place", token, body=body)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        order_no = result.get("order_no") or result.get("data", {}).get("order_no", "?")
        status = result.get("status") or result.get("data", {}).get("status", "?")
        print(f"[ev] {side} OK: order_no={order_no} status={status}")
        if result.get("message"):
            print(f"     msg: {result['message']}")


def cmd_cancel(args):
    token = _login.get_token()
    result = _http("POST", f"/api/orders/{args.order_no}/cancel", token, body={})
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"[ev] cancel {args.order_no}: success={result.get('success') or result.get('data', {}).get('success')}")


def cmd_asset(args):
    token = _login.get_token()
    result = _http("GET", "/api/asset", token)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        # 真实返回: {"code":0, "msg":"", "list":[{cash, total_asset, ...}]}
        items = result.get("list", [])
        data = items[0] if items else {}
        rows = [{
            "cash": data.get("cash", "?"),
            "available": data.get("available", "?"),
            "frozen_cash": data.get("frozen_cash", 0),
            "market_value": data.get("market_value", 0),
            "total_asset": data.get("total_asset", "?"),
        }]
        _print_table(rows, list(rows[0].keys()))
        ts = data.get("synced_at")
        if ts:
            print(f"\nsynced_at: {ts}")


def cmd_positions(args):
    token = _login.get_token()
    result = _http("GET", "/api/positions", token)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    items = result.get("list", result.get("data", result)) if isinstance(result, dict) else result
    if not isinstance(items, list):
        items = [items]
    rows = [{
        "stock_code": p.get("stock_code"),
        "vol": p.get("vol"),
        "avl": p.get("avl_vol"),
        "cost_price": p.get("cost_price"),
        "market_value": p.get("market_value"),
    } for p in items]
    _print_table(rows, ["stock_code", "vol", "avl", "cost_price", "market_value"])
    return
    _print_table(rows, ["stock_code", "volume", "avg_cost", "market_value", "pnl"])


def cmd_orders(args):
    token = _login.get_token()
    path = "/api/orders"
    if args.status:
        path += f"?status={args.status}"
    if args.date:
        sep = "&" if "?" in path else "?"
        path += f"{sep}date={args.date}"
    result = _http("GET", path, token)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    items = result.get("orders", result.get("list", result.get("data", result))) if isinstance(result, dict) else result
    if not isinstance(items, list):
        items = [items]
    rows = [{
        "order_no": o.get("order_no"),
        "stock_code": o.get("stock_code"),
        "type": o.get("order_type"),
        "price": o.get("price"),
        "volume": o.get("volume"),
        "traded": o.get("traded_volume", 0),
        "status": o.get("status"),
        "time": o.get("order_time"),
    } for o in items]
    _print_table(rows, ["time", "order_no", "stock_code", "type", "price", "volume", "traded", "status"])


def cmd_trades(args):
    token = _login.get_token()
    path = "/api/trades"
    if args.date:
        path += f"?date={args.date}"
    result = _http("GET", path, token)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    items = result.get("trades", result.get("list", result.get("data", result))) if isinstance(result, dict) else result
    if not isinstance(items, list):
        items = [items]
    rows = [{
        "trade_no": t.get("trade_id"),
        "order_no": t.get("order_no"),
        "stock_code": t.get("stock_code"),
        "type": t.get("order_type"),
        "price": t.get("price"),
        "volume": t.get("volume"),
        "time": t.get("trade_time"),
    } for t in items]
    _print_table(rows, ["time", "trade_no", "order_no", "stock_code", "type", "price", "volume"])


def cmd_stock(args):
    token = _login.get_token()
    # 查股票详情 (用 quote_cache latest snapshot + stocks table)
    snap_result = _http("GET", f"/api/stocks/{args.stock_code}", token)
    if args.json:
        print(json.dumps(snap_result, indent=2, ensure_ascii=False))
    else:
        data = snap_result.get("data", snap_result)
        for k, v in data.items():
            print(f"  {k}: {v}")


# ─────────────── main ───────────────


def main():
    parser = argparse.ArgumentParser(description="ev_api — EvTrade 交易 HTTP API")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--base", default=DEFAULT_BASE)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("buy", help="买入")
    p.add_argument("stock_code")
    p.add_argument("volume", type=int)
    p.add_argument("price", type=float)
    p.add_argument("--type", default="limit")
    p.set_defaults(func=cmd_buy)

    p = sub.add_parser("sell", help="卖出")
    p.add_argument("stock_code")
    p.add_argument("volume", type=int)
    p.add_argument("price", type=float)
    p.add_argument("--type", default="limit")
    p.set_defaults(func=cmd_sell)

    p = sub.add_parser("cancel", help="撤单")
    p.add_argument("order_no")
    p.set_defaults(func=cmd_cancel)

    p = sub.add_parser("asset", help="查资金 / 总资产")
    p.set_defaults(func=cmd_asset)

    p = sub.add_parser("positions", help="查持仓")
    p.set_defaults(func=cmd_positions)

    p = sub.add_parser("orders", help="查委托")
    p.add_argument("--status", help="pending/filled/cancelled/partial")
    p.add_argument("--date", help="YYYYMMDD")
    p.set_defaults(func=cmd_orders)

    p = sub.add_parser("trades", help="查成交")
    p.add_argument("--date", help="YYYYMMDD")
    p.set_defaults(func=cmd_trades)

    p = sub.add_parser("stock", help="查股票信息")
    p.add_argument("stock_code")
    p.set_defaults(func=cmd_stock)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()