# tasks — remap-price-type

## Commit 拆维度（按层 v6 纪律）

| # | 范围 | 触动文件 | commit hash | 验证 |
|---|---|---|---|---|
| 1 | 前端 UI | `client/src/constants/priceType.js`, `client/src/components/OrderForm.vue` | `b326eb7` | `npm run build` 通过 |
| 2 | 后端枚举 + ORM | `server/enums/trading.py`, `server/api/orders/schemas.py`, `server/models/orm.py` | `df0423e` | `python3 -c "from server.enums.trading import PriceType"` |
| 3 | 业务 + 测试 | `server/services/strategy/engine.py`, `server/tests/strategy/test_t0_endpoint_migration.py` | `7ffc11a` | `pytest server/tests/strategy/test_t0_endpoint_migration.py -q` |
| 4 | 迁移 + 文档 + 协议映射 | `server/migrations/2026-07-15-remap-price-type.py`, `openspec/specs/{trading,frontend,data-model}/spec.md`, `docs/server-rest-api.md`, `iquant/xtquant_api.py` | (本次提交) | 迁移脚本 dry-run + 跑通 + 校验 |

## Checklist

- [x] 1. **Commit 1** — 前端 UI: priceType.js + OrderForm.vue (8 处引用统一为 FIX_PRICE=0)
- [x] 2. **Commit 2** — 后端枚举 + ORM: trading.py PriceType 重写 + schemas.py default + orm.py default=0
- [x] 3. **Commit 3** — 业务 + 测试: engine.py price_type=11 → PriceType.FIX_PRICE (2 处) + 测试工厂同步
- [ ] 4. **Commit 4** — 迁移脚本 + 文档 + 柜台协议: 本次提交
  - `server/migrations/2026-07-15-remap-price-type.py` 新增（11/14→0, 5→1, 44→2, 幂等）
  - `openspec/specs/trading/spec.md` 价格类型码点表 + S-TRADE-001 示例
  - `openspec/specs/frontend/spec.md` REQ-FE-010 + 数据绑定场景
  - `openspec/specs/data-model/spec.md` orders 表 price_type 列 default + 注释
  - `docs/server-rest-api.md` POST /api/orders/place price_type 字段说明
  - `iquant/xtquant_api.py` price_type_map 加 "2" → MARKET_PEER_PRICE_FIRST
- [ ] 5. 迁移脚本 dry-run（先 SELECT 预览当前分布）
- [ ] 6. 执行迁移（UPDATE price_type 11/14 → 0，5 → 1，44 → 2）
- [ ] 7. 迁移后校验（无 0/1/2 之外的码点）
- [ ] 8. pytest server 跑通（关键: strategy / orders 路径）
- [ ] 9. 浏览器实测下单面板 UI（3 按钮 限价/最新价/市价 + vision 截图）
- [ ] 10. **不自动 push** — 等用户拍板 Q4