# Tasks — slim-stocks-table

## Commit 拆维度（按层 v6 纪律）

| # | 范围 | 触动文件 | 验证 |
|---|---|---|---|
| 1 | migration | `server/migrations/2026-07-12-slim-stocks-table.py` | `python3 server/migrations/2026-07-12-slim-stocks-table.py` 幂等跑通 + INFORMATION_SCHEMA 验证 |
| 2 | orm | `server/models/orm.py` | `python3 -c "from server.models.orm import Stock"` |
| 3 | repo | `server/repo/stocks.py` | `python3 -c "from server.repo import stocks"` |
| 4 | api + crawler | `server/api/stocks.py`, `server/crawler/sources/eastmoney.py`, `server/crawler/runner.py` | `python3 -c "from server.api import stocks; from server.crawler.sources import eastmoney; from server.crawler import runner"` |
| 5 | frontend | `client/src/api/stocks.js`, `client/src/stores/stocks.js`, `client/src/views/AdminStockConfig.vue` | 浏览器手测 admin 登录 → `/admin/stock-config` 看到 5 字段 + 弹窗 5 form item |
| 6 | docs | `openspec/specs/data-model/spec.md`, `openspec/specs/stocks/spec.md` | 字段表与 ORM 一致 |

## Checklist

- [x] 1. 写 spec-deltas/data-model.md（§13 字段表更新）
- [x] 2. 写 spec-deltas/stocks.md（REQ-STOCK-005 字段映射更新）
- [x] 3. **Commit 1** — migration: 备份 + DROP 9 + ADD 3
- [x] 4. **Commit 2** — orm: Stock 类
- [x] 5. **Commit 3** — repo: _ADMIN_EDITABLE_FIELDS + to_dict 系列
- [x] 6. **Commit 4** — api + crawler: StockUpdateRequest + eastmoney 映射 + runner WS payload
- [x] 7. **Commit 5** — frontend: 3 文件同步
- [x] 8. **Commit 6** — docs: data-model §13 + stocks spec REQ-STOCK-005
- [x] 9. 验证 migration 跑通（INFO_SCHEMA 验证）
- [x] 10. 验证 backend 能 import 不报字段错
- [x] 11. 验证前端 dev 编译过（vite serve 看 log）
- [x] 12. **不自动 push** — 等用户拍板

## 落地挂载清单（apply 阶段必跑，per J 节）

- [x] api 模块已就位（client/src/api/stocks.js）
- [x] Pinia store 已就位（client/src/stores/stocks.js）
- [x] router 路由已注册（client/src/router/index.js）
- [x] sidebar 菜单入口已挂（client/src/components/Sidebar.vue）
- [ ] 浏览器手测：admin 登录 → `/admin/stock-config` 看到 5 字段 + 弹窗 5 form item