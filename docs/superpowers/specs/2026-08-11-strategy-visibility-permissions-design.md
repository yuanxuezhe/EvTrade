# 策略可见性与权限矩阵 — 设计文档 (v125, 2026-08-11)

> **范围声明**:本 change 仅覆盖**策略模块(v125)**。策略模块改为**纯回测**(移除实盘/黑盒跟随)。
> 「策略下单 / 信号订阅→下单」是另一个子系统(Part 2),见 §8,另行设计。

## 1. 背景与目标

脚本策略系统 (v123/v124) 目前只有**脚本级** `is_public`,**策略级**没有显式可见性 —— 采用"派生自公开脚本 → 对其他用户可见、可回测、可实盘"的隐式规则。这与产品预期不符。

本次目标(v125)建立一套明确的、可测试的可见性/权限模型:

| 规则 | 说明 |
|---|---|
| R1 | 界面可为"开发的策略"设置 **私有 / 共有**(策略级 `is_public`) |
| R2 | 用户只能修改**属于自己的**策略;别人的(私有或共有)**都不能修改** |
| R3 | 别人的**私有**脚本/策略,其他人完全**看不到** |
| R4 | 别人的**公开脚本**:能看到源码 + 参数,只读;可据此**建自己的策略**(归自己,可再设公开/私有) |
| R5 | 别人的**公开策略**:列表可见(精简卡片:名称/标的/owner),**不能查看详情、不能回测、不能编辑** |
| R6 | 策略模块 = **纯回测**,只跑回测得到 best_params;**本模块不含实盘/黑盒跟随**(该能力移到 Part 2 策略下单) |
| R7 | **新建策略时必选标的(stock_code)**,策略只针对此标的回测;标的创建后不可改 |

> 注:曾讨论的"参数级 私有/公开"(params_schema 每参可见性)已**取消**,参数模型保持不变;可见性标记只作用于**策略实体**。

关键语义区分:
- **脚本级公开 = 开放源码可查看、只读、可实例化**;私有 = 完全不可见。
- **策略级公开 = 列表可见(精简)、可被"其他地方"(Part 2 策略下单)选择使用**;私有 = 完全不可见。
- 策略公开与否与脚本公开与否**相互独立**(公开策略可基于私有脚本)。
- 策略绑定单一标的:**回测固定用 `strategy.stock_code`**,不再由请求指定证券。

## 2. 数据模型

- 迁移 `strategy` 表增加 2 列:
  ```sql
  ALTER TABLE strategy ADD COLUMN is_public TINYINT NOT NULL DEFAULT 0 COMMENT '是否公开: 0=私有(默认) 1=公开(列表可见, 供策略下单选择)';
  ALTER TABLE strategy ADD COLUMN stock_code VARCHAR(16) NULL COMMENT '策略绑定标的 (新建时必填, 只针对此标的回测)';
  ```
  幂等(INFORMATION_SCHEMA 检查),仿 `2026-08-11-add-task-metric.py`。存量行 `stock_code=NULL` → 回测回退用请求的 stock_code(旧行为);新策略必填。
- `server/tables/strategy.py`:字段 8 → 10(`is_public`、`stock_code`),手改并同步 docstring。
- `server/services/script_strategy/_convert.py`:`strategy_row_to_dict` 输出 `"is_public": bool(...)`、`"stock_code"`。
- `create_strategy` 签名加 `stock_code: str`(必填),写入 strategy 行。
- 脚本层 `strategy_script.is_public` 已存在,不动。参数模型不变(无参数级可见性)。

## 3. 权限矩阵(新模块 `server/services/script_strategy/access.py`)

替换现有隐式规则 `_strategy_public_derived`(策略派生自公开脚本即放行),改为显式 `is_public` 判定。

| 操作 | 本人(owner) | 他人·公开策略 | 他人·私有策略 |
|---|---|---|---|
| 列表可见 | ✓(完整) | ✓(精简卡片) | ✗ |
| 查看详情 | ✓(含脚本/参数) | ✗(不含代码/best_params) | ✗ |
| 修改/删除/公开开关 | ✓ | ✗ | ✗ |
| 回测/批次/重测 | ✓ | ✗ `403 BACKTEST_FORBIDDEN` | ✗ `404 STRATEGY_NOT_FOUND` |

> 实盘/黑盒跟随不属于本 change(Part 2 策略下单)。

模块职责单一,提供:

```python
def strategy_is_public(strat) -> bool: ...
def public_view(strat) -> Dict:            # 精简视图: name/status/owner/is_public/stock_code/script 名
                                           # 不含 script 源码/params_schema/best_params
def resolve_strategy(strategy_id, user_id, is_admin=False) -> Optional[Row]:
    # 本人 / admin 返回;他人仅公开策略返回(用于列表/精简详情)
def require_backtest_access(strategy_id, user_id, is_admin=False) -> Row:
    # 仅 owner/admin;他人公开 → StrategyError("BACKTEST_FORBIDDEN");他人私有/不存在 → NO_STRATEGY
```

### 关键改动点

- `server/services/script_strategy/strategies.py`:
  - `list_strategies`:自己的 + 他人 `is_public=1` 的策略(他人返回 `public_view`);删除 public-derived 分支。
  - `get_strategy`:owner/admin 返回完整(含 script);他人公开返回 `public_view`;他人私有返回 None。
  - `update_strategy`:可更新字段加 `is_public`(仅 owner,已有 owner 校验)。
  - 删除 `_strategy_public_derived`;`_resolve_script` 保留(作者视角解析脚本用)。
- `server/services/script_strategy/batches.py`:
  - `create_backtest_batch` / `list_batches` / `list_batch_tasks` / `retest_batch`:改用 `require_backtest_access`(严格 owner)。
  - `create_backtest_batch`:标的用 `strat.stock_code`(存量 NULL 回退请求的 stock_code);仅 owner 可回测。
  - **移除实盘相关**:删除 `create_live_batch` 及其在 API 层的 `/live` 端点(策略模块纯回测;实盘能力 Part 2 重建)。

## 4. API 与错误码

- `server/api/script_strategy/schemas.py`:
  - `StrategyOut` 加 `is_public: bool = False`、`stock_code: Optional[str] = None`。
  - `StrategyCreate` 加 `stock_code: str`(必填)。
  - `StrategyOut.script` 改为 `Optional`(他人公开策略返回精简版,无 script 字段)。
  - `BacktestRequest.stock_code` 改为 `Optional`(标的由策略绑定决定,若提供须匹配否则 `400 STOCK_MISMATCH`)。
- `server/api/script_strategy/strategies.py`:
  - `backtest`/`batches`/`retest` 端点错误码映射加 `BACKTEST_FORBIDDEN → 403`。
  - **删除 `live` 端点**;`LiveRequest` / `LiveResponse` schema 移除(或留待 Part 2 重建)。
- 隐私原则:他人私有策略在列表/详情/回测一律 `404 STRATEGY_NOT_FOUND`(不泄漏存在性);他人公开策略的受限操作(回测)返回 `403`,因为用户已在列表看到它。

## 5. 前端

- **ScriptTask.vue**(策略/任务页):
  - **新建策略表单**:`{name, script_id, 标的 stock_code}`,标的必选(策略只针对此标的)。
  - 策略列表区分「我的 / 公开」:我的 → 现有操作(回测/重测/批次) + 新增「公开/私有」开关(仅 owner)+ 显示标的;他人公开策略 → **只读精简卡片**(名称/标的/owner),无回测/编辑/实盘入口。
  - **回测表单**:不再有标的输入,固定用 `strategy.stock_code`。
  - **移除「实盘」按钮 + live 徽章逻辑**。
  - 由列表返回的 `is_public` + `owner` 判定当前用户视角。
- **ScriptDev.vue**(策略开发页):
  - 他人公开脚本:表单**只读**(禁用编辑/删除/保存按钮),符合 R4"能看到内容但无权修改"。

## 6. 测试

服务层测试(新增于 `tests/server/strategy/test_strategy_v123_service.py` 或独立文件):
- `list_strategies` 显示自己的 + 他人公开策略;他人公开项为精简视图(无 script/best_params)。
- 非 owner 对公开策略 `backtest` → `BACKTEST_FORBIDDEN`;对私有策略 → `NO_STRATEGY`(404)。
- `get_strategy`:他人公开返回精简视图;他人私有返回 None。
- `update_strategy` 切换 `is_public` 仅 owner 生效。
- `create_strategy` 缺 stock_code → 校验失败;存量 NULL 策略回退请求标的。
- 标的失配:回测请求提供 stock_code 且 ≠ 策略绑定标的 → `STOCK_MISMATCH`(400)。
- 迁移幂等(`test_migration_idempotent` 需兼容新列)。
- 移除 live 相关测试(策略模块纯回测)。

## 7. 规格文档

`openspec/specs/strategy/spec.md` 补 **REQ-STRAT-019: 策略可见性与权限矩阵(v125, 2026-08-11)**:
- 数据模型:`strategy.is_public` + `strategy.stock_code`(迁移);`create_strategy` 必填标的。
- 权限矩阵(上表);策略模块纯回测,移除 `/live`。
- 错误码:`403 BACKTEST_FORBIDDEN` / `404 STRATEGY_NOT_FOUND` / `400 STOCK_MISMATCH`。
- 场景:作者发布公开策略 / 非 owner 回测被拒 / 私有策略不可见 / 公开策略精简卡片。

## 8. 范围外(YAGNI)

- **Part 2「策略下单」另行设计**(2026-08-11 拆分):
  - 策略交易组新增「策略下单」页(4 面板:策略下单 / 行情面板 / 策略母单 / 委托子单)。
  - 新表 `strategy_order`(母单,与 `t0_tasks` 分表);`task_id` 走统一序号生成器(`order_no_seq`,t0 与母单共用一套)。
  - 子单进 `orders`,`task_id` 关联母单;子单 `user_def` = 策略名(非 'T0')。
  - 复用已有链路:strategy_exec `LiveRunner` 跑策略 → `publish_signal` → RabbitMQ → EvTrade `signal_consumer` → `/api/orders/place`。
- 不引入"策略复制/克隆"机制(方案 B 已否决)。
- 不做"跟随关系表"。
- 不改脚本级 `is_public` 语义(开放源码只读,已符合 R4)。
- **不做参数级 私有/公开**(已取消);`order_attr` / 下策略单流程不属于本 change。
- 策略绑定标的创建后不可改(保持简单;需要时再放开)。
