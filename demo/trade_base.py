#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
examples/trade_base.py

纯交易基类 —— 只负责登录 + 下单 + 撤单 + 查询 (REST)。
不碰 WS、不订阅行情。需要行情订阅请用 quote_base.QuoteBase 组合。

用法:
    from trade_base import TradeBase

    tb = TradeBase("http://127.0.0.1:8000", "admin", "admin123")
    print(tb.token)                 # 触发登录
    print(tb.asset())
    print(tb.positions())
    print(tb.buy("600519.SH", 100.0, 100))
    print(tb.cancel(order_no, trd_date=tb.active_trd_date()))
"""
from __future__ import annotations

import logging
from typing import List, Optional

import requests

log = logging.getLogger("trade_base")

# 23=买 24=卖 (与后端 PlaceOrderRequest.order_type 一致)
_BUY, _SELL = "23", "24"


class TradeBase:
    """交易基类:鉴权 + REST 下单/撤单/查询,不碰 WS。"""

    def __init__(self, base_url: str, username: str, password: str,
                 trd_date: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.trd_date = trd_date            # 撤单/查委托默认用,None = 自动取
        self._token: Optional[str] = None

    # ──────────── 公开:鉴权 ────────────
    @property
    def token(self) -> str:
        """懒登录:首次访问触发 login,之后直接返回。"""
        if not self._token:
            self.login()
        return self._token

    def login(self) -> str:
        resp = requests.post(
            f"{self.base_url}/api/auth/login",
            data={"username": self.username, "password": self.password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=5,
        )
        resp.raise_for_status()
        body = resp.json()
        self._token = body["access_token"]
        log.info("✅ 登录 user=%s", body["user"]["username"])
        return self._token

    # ──────────── 公开:下单 ────────────
    def buy(self, code: str, price: float, volume: int,
            price_type: int = 1, t0_coefficient: float = 1.0,
            user_def: str = "") -> dict:
        """买入。price_type: 1=限价 2=市价。"""
        return self._place(code, _BUY, price, volume, price_type,
                           t0_coefficient, user_def)

    def sell(self, code: str, price: float, volume: int,
             price_type: int = 1, t0_coefficient: float = 1.0,
             user_def: str = "") -> dict:
        """卖出。"""
        return self._place(code, _SELL, price, volume, price_type,
                           t0_coefficient, user_def)

    def cancel(self, order_no: str, trd_date: Optional[str] = None) -> dict:
        """撤单。trd_date 默认取 self.trd_date 或 active_trd_date()。"""
        td = trd_date or self.trd_date or self.active_trd_date()
        return self._req("DELETE", f"/api/orders/{order_no}",
                         params={"trd_date": td})

    # ──────────── 公开:查询 ────────────
    def positions(self, stock_code: Optional[str] = None) -> List[dict]:
        return self._req("GET", "/api/positions",
                         params={"stock_code": stock_code} if stock_code else None
                         ).get("list", [])

    def asset(self) -> dict:
        lst = self._req("GET", "/api/asset").get("list", [])
        return lst[0] if lst else {}

    def orders(self, stock_code: Optional[str] = None,
               status: Optional[str] = None,
               all_dates: bool = False) -> List[dict]:
        params = {}
        if stock_code: params["stock_code"] = stock_code
        if status:     params["status"] = status
        if all_dates:  params["all"] = "true"
        return self._req("GET", "/api/orders",
                         params=params or None).get("list", [])

    def active_trd_date(self) -> str:
        """当前激活交易日(从 orders 列表里反推一条)。"""
        lst = self._req("GET", "/api/orders",
                        params={"limit": 1}).get("list", [])
        if lst and lst[0].get("trd_date"):
            return lst[0]["trd_date"]
        return self.trd_date or ""

    # ──────────── 私有:HTTP(401 自动重登一次) ────────────
    def _req(self, method: str, path: str, *,
             params=None, json_body=None) -> dict:
        url = f"{self.base_url}{path}"
        for attempt in (1, 2):
            resp = requests.request(
                method, url,
                params=params, json=json_body,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=10,
            )
            if resp.status_code == 401 and attempt == 1:
                log.warning("token 过期,自动重登")
                self.login()
                continue
            resp.raise_for_status()
            return resp.json()
        return {}

    def _place(self, code, side, price, volume, price_type,
               t0_coefficient, user_def) -> dict:
        return self._req("POST", "/api/orders/place", json_body={
            "user_def": user_def, "stock_code": code,
            "order_type": side, "price_type": price_type,
            "price": price, "volume": volume,
            "t0_coefficient": t0_coefficient,
        })
