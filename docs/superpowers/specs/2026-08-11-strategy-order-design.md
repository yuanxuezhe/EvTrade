# 策略下单(母单)— 设计文档 (v126, 2026-08-11)

> 承接 v125「策略可见性/纯回测」Part 2(§8 拆出)。策略模块 v125 后为**纯回测**;
> 本 change 恢复**实盘下单**:用户对已回测出 best_params 的策略创建**母单**并启动实盘,
> 策略触发的信号自动下真实子单,子单归因到母单。

## 1. 背景与目标

v125 将策略模块改为纯回测并删除了 EvTrade 的 `/live` 端点,但 strategy_exec 的实盘链路
(LiveRunner + signal publisher + /internal/run-task mode=live)完整保留。本次(v126)的目标:

- 用户可为自己的策略创建 **策略母单 `strategy_order`**(多个母单可选同一策略);
- 每个母单有独立 `task_id`(统一 `order_no_seq` 机制生成);母单可**重复启停**;
- 启动母单 → 复用 `strategy_task` 做 live 执行(转发 strategy_exec LiveRunner);
- 策略触发信号 → signal_consumer 下**真实子单**,子单 `orders.task_id = 母单.task_id`、
  `user_def = 策略名`、`strategy_type = 2`;
- 新增独立页「策略下单」(`/strategy-order`),4 面板:策略下单 / 行情面板 / 策略母单 / 委托子单。

关键语义:
- **参数对外不可见**:母单直接用 `strategy.best_params` 运行实盘,不展示/不修改;
- **无 best_params 的策略不可选**:必须先回测出最佳参数才能下单;
- **母单可重复启停**:启动/停止只改母单状态,多次运行的子单累积到同一母单;
- **仅 owner 可建母单**:他人公开策略的 best_params 不外露(v125 R5 一致)。

## 2. 数据模型

### 2.1 新表 `strategy_order`(母单)

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | INT PK 自增 | 行主键 |
| `task_id` | INT NOT NULL UNIQUE | 母单对外编号(`order_no_seq` 生成器 `strategy_order`);子单 `orders.task_id` 指向它 |
| `user_id` | INT NOT NULL | owner |
| `strategy_id` | INT NOT NULL | 关联策略 |
| `stock_code` | VARCHAR(16) NOT NULL | 冗余自 `strategy.stock_code`(展示/过滤) |
| `status` | VARCHAR(16) NOT NULL | `stopped`(初始)/ `running` / `closed`(终态) |
| `active_task_id` | INT NULL | 当前 live `strategy_task.id`(停止时转发 `/internal/stop-task` 用) |
| `run_count` | INT NOT NULL DEFAULT 0 | 累计启动次数 |
| `last_started_at` | DATETIME NULL | |
| `last_stopped_at` | DATETIME NULL | |
| `created_at` / `updated_at` | DATETIME NOT NULL | |
| `closed_at` | DATETIME NULL | |

索引:`UNIQUE(task_id)`、`KEY(user_id)`、`KEY(strategy_id)`。

- tables-codegen 生成 `server/tables/strategy_order.py`。
- 迁移(幂等,INFORMATION_SCHEMA 检查,仿 v125 迁移):
  - 建 `strategy_order` 表;
  - `order_no_seq` 初始化 `strategy_order` 生成器(INSERT IGNORE);
  - `orders.strategy_type` 列 COMMENT 更新(0=普通 1=快速做T 2=策略下单),列类型不变(INT)。

### 2.2 `orders.strategy_type` 扩到 2

- `server/api/orders/schemas.py`: `strategy_type: Literal[0, 1]` → `Literal[0, 1, 2]`;
  `OrderOut.strategy_type` 注释同步。
- `server/models/orm.py` + `server/schema.yml`: COMMENT/文档同步(0=普通单 1=快速做T 2=策略下单)。
- 前端 orderCalc.js / push helpers 已通用透传 `strategy_type` 与 `task_id`,无需改。

### 2.3 `strategy_task` 不改结构

- live 任务照旧 `create_task(mode='live', strategy_id, stock_code, params=best_params)`。
- v125 只删了 API 层 `/live`;表字段本就支持 live 模式,无结构变更。
- 母单**不存 params**(参数不可见):每次启动读当前 `strategy.best_params` → 快照到
  `strategy_task.params`。重启即用最新 best_params。

## 3. 信号链路(方案 B:signal payload 携带母单 task_id)

```
EvTrade 启动母单 ─→ POST strategy_exec /internal/run-task
    {mode:'live', task_id, user_id, strategy_id, script_id, stock_code,
     params, parent_task_id: 母单.task_id, strategy_name: 策略名}
  → start_live_runner(透传 parent_task_id, strategy_name)
  → LiveRunner → _set_task_meta(task_id, user_id, script_id, mode='live',
                                parent_task_id, strategy_name)
  → 用户脚本 buy_signal/sell_signal → Signal(+parent_task_id, +strategy_name)
  → signal_to_payload(自动含新字段) → RabbitMQ
  → EvTrade signal_consumer:
       task_id        = payload.parent_task_id   # 母单 task_id → orders.task_id
       user_def       = payload.strategy_name     # 策略名
       strategy_type  = 2
```

strategy_exec 改动(均为可选字段,回测路径签名兼容):

- `strategy_exec/signal/types.py`:`Signal` 加
  `parent_task_id: Optional[int] = None`、`strategy_name: str = ""`;
  `signal_to_payload` 用 `asdict` 自动序列化,无需额外处理。
- `strategy_exec/engines/backtrader/adapter.py`:`_set_task_meta` 加两个带默认值参数;
  `_publish` 构造 Signal 带上。
- `strategy_exec/engines/backtrader/live.py`:`LiveRunner.__init__` 与 `start_live_runner`
  透传 `parent_task_id`、`strategy_name`;`_run` 里 `_set_task_meta` 传入。
- `strategy_exec/api/internal.py`:`RunTaskRequest` 加
  `parent_task_id: Optional[int] = None`、`strategy_name: Optional[str] = None`;
  live 分支透传给 `start_live_runner`。

EvTrade `server/services/strategy/signal_consumer.py`:

- 回测信号(`mode == 'backtest'`,parent_task_id=None)仍跳过,不下单;
- INFO 仍跳过;
- BUY/SELL 下单请求改为:
  ```python
  json={
      "stock_code": payload.get("stock_code"),
      "order_type": order_type,            # 23=买 24=卖
      "price_type": price_type,
      "price": payload.get("price"),
      "volume": payload.get("volume"),
      "remark": f"strategy-{payload.get('task_id')}-{trace_id[:8]}",
      "strategy_type": 2,                  # 策略下单
      "task_id": payload.get("parent_task_id") or None,   # 母单 task_id
      "user_def": payload.get("strategy_name") or "",      # 策略名
  }
  ```

## 4. EvTrade API(script_strategy 新增 `strategy_orders` 子模块)

文件:
- `server/services/script_strategy/strategy_orders.py`(服务层)
- `server/api/script_strategy/strategy_orders.py`(REST 层)
- `server/api/script_strategy/schemas.py` 加 `StrategyOrderOut`/`StrategyOrderCreate`/`StartStopResponse`
- `server/services/script_strategy/__init__.py` 统一入口导出

端点(前缀 `/api/script-strategy`):

| 端点 | 行为 |
|---|---|
| `POST /strategy-orders` | body `{strategy_id}`;校验策略存在 + owner(非 admin 他人 → 404 `STRATEGY_NOT_FOUND`)+ `best_params` 非空(否则 400 `NO_BEST_PARAMS`)→ `next_seq("strategy_order")` 生成 task_id → 建母单(初始 `stopped`)→ 201 |
| `GET /strategy-orders` | 我的母单列表(admin 全部),JOIN 策略名 + 子单数(`orders.task_id=母单.task_id` COUNT) |
| `GET /strategy-orders/{id}` | 详情(含策略名/标的/状态/run_count/子单数) |
| `POST /strategy-orders/{id}/start` | 校验状态非 `closed`(否则 409 `INVALID_STATE`)→ 读 `strategy.best_params`(空 → 400 `NO_BEST_PARAMS`)→ `create_task(mode='live', strategy_id, stock_code=strategy.stock_code, params=best_params)` → 转发 `/internal/run-task`(mode=live, parent_task_id=母单.task_id, strategy_name=策略名)→ `status=running`,记 `active_task_id`, `run_count+1`, `last_started_at` |
| `POST /strategy-orders/{id}/stop` | 校验 `running` 且 `active_task_id`(否则 409 `INVALID_STATE`)→ 转发 `/internal/stop-task(active_task_id)` → `status=stopped`, `active_task_id=NULL`, `last_stopped_at` |
| `POST /strategy-orders/{id}/close` | 校验非 `running`(否则 409)→ `status=closed`, `closed_at`(终态,不硬删,保审计) |

错误码:`STRATEGY_NOT_FOUND`(404)/`NO_BEST_PARAMS`(400)/`INVALID_STATE`(409)/`FORBIDDEN`(403)。

权限:仅 owner(或 admin)可建/启/停/关母单;他人私有策略 → 404 不泄漏存在性。
**他人公开策略的 best_params 不外露(public_view 精简),不可建母单。**

## 5. 前端

- 新页 `client/src/views/StrategyOrder.vue`,路由 `/strategy-order`,
  NavBar(桌面)加「策略下单」入口;BottomNav 不加(移动端空间有限)。
- 4 面板:
  1. **策略下单**:下拉选自己的策略(**仅 best_params 非空可选中**,空时置灰提示
     「需先回测出最佳参数」)→ 显示标的/「已回测」标记(参数不可见)→「创建母单」。
  2. **行情面板**:复用 `QuotePanel.vue`,跟随选中母单/策略的 `stock_code`。
  3. **策略母单**:列表(`GET /strategy-orders`),每行 = 母单 task_id / 策略名 / 标的 /
     状态徽章 / 启动次数 / 子单数 / [启动|停止] / 关闭。选中行联动子单面板。
  4. **委托子单**:`holdings.orders.filter(o => o.strategy_type===2 && Number(o.task_id)===选中母单.task_id)`
     (T0Trade 同款本地缓存过滤,实时)。
- **T0 视图防御过滤**:`T0Trade.vue` 委托过滤(约 470 行)加 `strategy_type !== 2` 条件,
  与策略单按 strategy_type 互斥,防 task_id 撞号串视图。
- 状态徽章:stopped=默认 / running=进行中 / closed=已关闭;`running` 时禁用「关闭」,
  `closed` 禁用「启动」。

## 6. 测试

- 服务层(`tests/server/strategy/`):
  - 母单状态机:create→start→stop→close;非法转移(running 再 start / 非 running stop / running close)→ 409。
  - 权限:他人策略建母单 → 404;非 owner 操作 → 404/403。
  - `best_params` 空 → 400;start 时 `strategy_task.params` 取自 `strategy.best_params`。
  - `task_id` 来自 `order_no_seq` 的 `strategy_order` 生成器且唯一。
- signal_consumer:BUY/SELL signal → place 请求参数映射
  (`parent_task_id`→task_id、`strategy_name`→user_def、`strategy_type=2`);回测/INFO 仍跳过。
- strategy_exec:`Signal.payload` 含 `parent_task_id`/`strategy_name`;run-task 透传;回测路径签名兼容。
- 迁移幂等:`strategy_order` 表 + `order_no_seq` 生成器 + `strategy_type` COMMENT 复跑不抛错。
- 前端:StrategyOrder 组件测试(mock API);T0Trade 过滤互斥断言(`strategy_type!==2`)。

## 7. 规格文档

`openspec/specs/strategy/spec.md` 补 **REQ-STRAT-020: 策略母单与实盘下单(v126, 2026-08-11)**:
- 数据模型:`strategy_order` 表 + 生成器;子单 `orders.task_id=母单.task_id`、`strategy_type=2`、`user_def=策略名`。
- 参数:对外不可见,直接使用 `strategy.best_params`;无 best_params 不可选/不可启动。
- 生命周期:母单可重复启停(stopped/running/closed)。
- 复用链路:strategy_exec LiveRunner → publish_signal(带 parent_task_id/strategy_name)→ signal_consumer → /orders/place。
- 错误码:`404 STRATEGY_NOT_FOUND` / `400 NO_BEST_PARAMS` / `409 INVALID_STATE`。
- 场景:创建母单 / 启动实盘 / 信号下子单归因 / 停止 / 关闭。

## 8. 范围外(YAGNI)

- 母单不做资金/持仓/盈亏聚合(订单归因是母单职责;PnL 属 T0 报表域,不混入)。
- 不做下单量/资金管理(脚本自带 `volume`)。
- 不做策略复制/克隆、不做止损风控。
- 不做他人公开策略的下单(best_params 不外露;仅 owner)。
- 不提供 DELETE 硬删(close 保审计;子单 task_id 是历史归属,不置空)。
