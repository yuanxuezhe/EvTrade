# spec-deltas / trading — remap-price-type

> 本 change 已直接合并到 `openspec/specs/trading/spec.md`。
> 此处留痕记录本 change 改动的具体章节与原文片段，便于 review/回滚。

## REQ-TRADE-002 第 31 行（价格类型码点表）

**Before**:
```
- `price_type` 数字：`5=最新价 11=指定价 14=对手价 44=市价 ...`
```

**After**:
```
- `price_type` 数字：`0=限价(xtconstant.FIX_PRICE) 1=最新价(xtconstant.LATEST_PRICE) 2=市价(xtconstant.MARKET_PEER_PRICE_FIRST, 对手方最优价, 吃档 1)`（v__: 与 xtconstant 柜台协议 1:1 对齐）
```

## S-TRADE-001 第 592 行（限价买单示例）

**Before**:
```
When `POST /api/orders/place {stock_code:"600030.SH", order_type:"23", volume:100, price:12.34, price_type:11}`
```

**After**:
```
When `POST /api/orders/place {stock_code:"600030.SH", order_type:"23", volume:100, price:12.34, price_type:0}`
```

## 影响

- `server/enums/trading.py::PriceType` 整类替换 (FIX_PRICE=0 / LATEST_PRICE=1 / MARKET_PEER_PRICE_FIRST=2)
- `server/api/orders/schemas.py::PlaceOrderRequest.price_type` default = `PriceType.FIX_PRICE`
- `server/models/orm.py::Order.price_type` 列 default = `0`
- 历史数据由 `server/migrations/2026-07-15-remap-price-type.py` 迁移 (11/14→0, 5→1, 44→2, 幂等)