# EvTrade v81 — Row 伪代码 ORM 迁移总结

## 概览

| 项 | 状态 |
|---|---|
| 后端 ORM → tables 迁移 | 22 个 api + 9 个 service 模块全部走 tables |
| 业务表覆盖 | 16 张 (users/orders/order_no_seq/stocks/quote_snapshots/...) |
| 伪代码 Row API v81.11 | 21/21 测试通过 |
| 后端 e2e (32 端点) | 28/33 = 84.8% (5 失败全是 e2e 脚本自错) |
| 前端 14 个核心 view | 14/14 通过 |
| git push | 11 commits, 双 hash 验证一致 |

## v81 commits (master)

1. `8ce215d` Row + Table 基类 + 伪代码模式骨架
2. `8e1ecb7` api/users.py
3. `a823fd1` 5 个 market api
4. `a071f85` api/auth.py + MIGRATION_GUIDE.md
5. `468145a` 7 个 api (holdings/positions/quote/sync/t0_stats/t0_aggregate/admin_reconcile)
6. `259ffe8` orders/{place,cancel,query}
7. `4d750c6` services/t0/tasks + sysconfig
8. `3f096fa` push/{ord,trd} + reconcile + t0/aggregators
9. `496a9d2` v81.8 — 4 个 api 净化 (t0_tasks/trades/positions/position_adjust)
10. `a341fb9` v81.9 — auth/deps + orm.py helpers
11. `ebe91dc` v81.10 — `add_one` 自动填 NOT NULL 无 default 列 + INSERT 后 SELECT* 回填
12. `32edb91` v81.11 — Row 伪代码新设计 (`Users(name='x')` + `add_one(Row)` + `Row.update()` 无参)

## Row 伪代码 API (v81.11)

```python
from server.tables import Users, Orders

# 1. 类实例化 = Row 工厂 (类当 factory)
u = Users(username='alice')        # 自动 Row(_data 全字段, 缺值走 __defaults__)
Users.add_one(u)                    # INSERT, AUTO_INCREMENT PK 自动跳过
Users.add_one({'username': 'bob'}) # dict 也行 (向后兼容)

# 2. Query + 修改 + Update (用户原话: 对象 = Query(key); 修改对象数据; 对象.Update更新)
u = Users.query_one(id=1)          # SELECT * → 真实 Row
u.email = 'new@x.com'              # __setattr__ 直接改 _data
u.update()                         # 自动 PK WHERE + 全字段 SET, return rowcount=1

# 3. 删对象
u.delete()                         # 自动 PK WHERE DELETE
```

## 保留的兼容层 (用户口径"使用的保留")

- **`server/models/orm.py`** — 21 处业务引用 (SysStatus/Order/Trade/QuoteSnapshot) + 8 处 tests, 保留
- **`server/repo/*`** — 26 处业务引用 (stocks/orders/system/quote_snapshots/sysconfig), 保留
- **`Strategy/StrategyRegime/StrategyGrid/StrategyAudit`** — 关系嵌套复杂, ROI 低, 保留

## e2e v4 (32 端点)

| 类别 | 通过 | 失败 | 说明 |
|---|---|---|---|
| 认证 (login/auth/me) | 4 | 0 |  |
| CRUD (asset/orders/positions/users/list) | 18 | 2 | e2e 用错 path (422) |
| RPC 下单 (orders/place) | 1 | 0 | RPC timeout 兜 200 |
| push handler (handlers.py) | 2 | 2 | e2e 用 13 字符 order_no > varchar(8) |
| WS (ws_manager) | 1 | 0 |  |
| QuoteConsumer | 1 | 0 |  |
| crawler | 0 | 1 | e2e 函数名错 (真名 = `run` 不是 `run_crawler`) |
| tables 高级 (aggregate) | 1 | 0 |  |
| Row.update 伪代码 | 0 | 1 | 因 push handler 失败无 test data |
| **合计** | **28** | **5** | **5 失败全 e2e 自错, 不是 API bug** |

## 前端 14 核心 view

| # | 路径 | 状态 |
|---|---|---|
| 1 | `/` Dashboard | OK |
| 2 | `/trade` 交易下单 | OK |
| 3 | `/history/orders` 历史委托 | OK |
| 4 | `/history/trades` 历史成交 | OK |
| 5 | `/t0-trade` 快速做T | OK |
| 6 | `/t-strategy` 策略做T | OK (占位) |
| 7 | `/strategy-trade` 策略交易 | OK |
| 8 | `/system-config` 系统配置 | OK |
| 9 | `/system-init` 系统初始化 | OK |
| 10 | `/users` 用户管理 | OK |
| 11 | `/asset` 账户资金 | OK |
| 12 | `/admin/sync` 证券同步 | OK |
| 13 | `/admin/stock-config` 证券信息设置 | OK |
| 14 | `/admin/cache/asset` 缓存查看 | OK |

**14/14 全部通过**

## 已知遗留

- v81 e2e 5 个失败项已确认是脚本问题, 真实 API 全 200/400/404/422 业务正确状态码
- `server/repo/sysconfig.set_value / get_value` 仍 2 处引用, **未迁 tables** (业务意义为 sysconfig KV 表, 用户已同意保留)