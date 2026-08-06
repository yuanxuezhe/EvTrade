# spec-deltas / frontend — remap-price-type

> 本 change 已直接合并到 `openspec/specs/frontend/spec.md`。

## REQ-FE-010 第 736 行（限价单小数支持）

**Before**:
```
- 限价单（`price_type === PriceType.LIMIT`）委托价格输入支持 2 位小数（A 股最小变动单位 0.01 元）
```

**After**:
```
- 限价单（`price_type === PriceType.FIX_PRICE`）委托价格输入支持 2 位小数（A 股最小变动单位 0.01 元）
```

## REQ-FE-019 数据绑定场景第 1156/1159 行

**Before**:
```
- **GIVEN** `v-model="form.price_type"` 与 `form.price_type` 联动委托价格 input 的 `disabled` / `placeholder` / `PriceType.LIMIT` 校验
- ...
- **AND** 后端 API 调用不变 (`{price_type: 11|5|14|44}`)
```

**After**:
```
- **GIVEN** `v-model="form.price_type"` 与 `form.price_type` 联动委托价格 input 的 `disabled` / `placeholder` / `PriceType.FIX_PRICE` 校验
- ...
- **AND** 后端 API 调用协议 `{price_type: 0|1|2}`（v__: 与 xtconstant 柜台协议 1:1 对齐）
```

## REQ-FE-019 Migration 第 1258 行

**Before**:
```
- 数据流不变 (`v-model="form.price_type"` + `PriceType.LIMIT` 校验逻辑不动); 后端协议不变 (`{price_type: 11|5|14|44}`)
```

**After**:
```
- 数据流不变 (`v-model="form.price_type"` + `PriceType.FIX_PRICE` 校验逻辑不动); 后端协议 `{price_type: 0|1/2}`（v__: 与 xtconstant 柜台协议 1:1 对齐）
```

## 影响

- `client/src/constants/priceType.js` `PriceType={FIX_PRICE:0, LATEST_PRICE:1, MARKET_PEER_PRICE_FIRST:2}` + `priceTypeOptions` 3 项
- `client/src/components/OrderForm.vue` 8 处引用统一为 `PriceType.FIX_PRICE`