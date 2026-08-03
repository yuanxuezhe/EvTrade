# script-strategy — 实施清单

按 opsx 规范拆成 13 步细粒度任务,每完成一项立即 8 列汇报。

| # | 任务 | 预计时间 | 状态 |
|---|---|---|---|
| 1 | 写 OpenSpec proposal + tasks.md + spec-deltas (3 份) | 5 min | ✅ done |
| 2 | 设计 2 张新表 schema (DDL) | 3 min | ⏳ pending |
| 3 | 写 migration + 跑通 + 重跑 gen_tables.py 生成 server/tables/ | 5 min | ⏳ pending |
| 4 | 实现 server/strategy/lib/ 指标层 + doorder/docancel wrapper | 8 min | ⏳ pending |
| 5 | 实现 script sandbox 加载器 | 5 min | ⏳ pending |
| 6 | 实现回测引擎 (on_bar + 参数组合 + PnL) | 8 min | ⏳ pending |
| 7 | 实现实盘引擎 (quote_consumer + on_tick + doorder) | 8 min | ⏳ pending |
| 8 | 实现 service 层 (script CRUD + task 调度) | 5 min | ⏳ pending |
| 9 | 实现 API endpoints | 5 min | ⏳ pending |
| 10 | 前端 ScriptDev.vue (代码编辑器 + 参数 schema) | 8 min | ⏳ pending |
| 11 | 前端 ScriptTask.vue (任务列表 + 回测/实盘运行 + 收益) | 8 min | ⏳ pending |
| 12 | 前端 api 客户端 + 路由注册 + 导航菜单 | 5 min | ⏳ pending |
| 13 | main.py 注册 + 单元测试 + 文档归档 | 5 min | ⏳ pending |

## 关键里程碑

- T1 (任务 3 完成): 2 张表落 DB,`server/tables/strategy_script.py` 与 `strategy_task.py` 自动生成
- T2 (任务 7 完成): 后端核心能力就绪(可手动写脚本跑回测 + 实盘)
- T3 (任务 12 完成): 前后端贯通,用户可端到端使用

## 不在范围

- T0 模块(`server/services/strategy/t0/`)改造 — 完全不动
- 已有 `Strategy` / `StrategyRegime` / `StrategyGrid` 表结构 — 不动
- 已有前端 `StrategyTrade.vue` — 不动,新模块独立页面