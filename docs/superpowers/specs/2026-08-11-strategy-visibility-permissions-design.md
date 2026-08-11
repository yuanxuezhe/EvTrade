# 策略可见性与权限矩阵 — 设计文档 (2026-08-11)

## 1. 背景与目标

脚本策略系统 (v123/v124) 目前只有**脚本级** `is_public`(公开脚本对其他用户可见源码、可据此建策略),**策略级**没有显式可见性 —— 采用"派生自公开脚本 → 对其他用户可见、可回测、可实盘"的隐式规则。这与产品预期不符。

本次目标(v125)建立一套明确的、可测试的可见性/权限模型:

| 规则 | 说明 |
|---|---|
| R1 | 界面可为"开发的策略"设置 **私有 / 共有** |
| R2 | 用户只能修改**属于自己的**策略;别人的(私有或共有)**都不能修改** |
| R3 | 别人的**私有**脚本/策略,其他人完全**看不到** |
| R4 | 别人的**公开脚本**:能看到源码 + 参数,只读;可据此**建自己的策略**(归自己,可再设公开/私有) |
| R5 | 别人的**公开策略**:不需看到详细参数,只喂个性化参数(如自定义证券代码),用**作者的参数实盘** |
| R6 | 别人的公开策略:**无法自己回测**,只能使用作者参数实盘 |

关键语义区分:
- **脚本级公开 = 开放源码可查看、只读、可实例化**;私有 = 完全不可见。
- **策略级公开 = 黑盒实盘跟随**(作者 best_params + 跟随者个性化输入);私有 = 完全不可见。
- 策略公开与否与脚本公开与否**相互独立**(公开策略可基于私有脚本)。

## 2. 数据模型

- 迁移 `strategy` 表增加列:
  ```sql
  ALTER TABLE strategy ADD COLUMN is_public TINYINT NOT NULL DEFAULT 0 COMMENT '是否公开: 0=私有(默认) 1=公开(可被黑盒实盘使用)';
  ```
  幂等(INFORMATION_SCHEMA 检查),仿 `2026-08-11-add-task-metric.py`。
- `server/tables/strategy.py`:字段 8 → 9(`is_public`),手改并同步 docstring。
- `server/services/script_strategy/_convert.py`:`strategy_row_to_dict` 输出 `"is_public": bool(d.get("is_public", 0))`。
- 脚本层 `strategy_script.is_public` 已存在,不动。

## 3. 权限矩阵(新模块 `server/services/script_strategy/access.py`)

替换现有隐式规则 `_strategy_public_derived`(策略派生自公开脚本即放行),改为显式 `is_public` 判定。

| 操作 | 本人(owner) | 他人·公开策略 | 他人·私有策略 |
|---|---|---|---|
| 列表可见 | ✓(完整) | ✓(精简卡片) | ✗ |
| 查看详情 | ✓(含脚本/参数) | ✗(不含代码/best_params) | ✗ |
| 修改/删除/公开开关 | ✓ | ✗ | ✗ |
| 回测/批次/重测 | ✓ | ✗ `403 BACKTEST_FORBIDDEN` | ✗ `404 STRATEGY_NOT_FOUND` |
| 实盘 | ✓(自己的 best_params/参数) | ✓ 黑盒跟随(作者 best_params + 跟随者 stock_code) | ✗ `404` |

模块职责单一,提供:

```python
def strategy_is_public(strat) -> bool: ...
def public_view(strat) -> Dict:            # 精简视图: name/status/owner/is_public/script 名
                                           # 不含 script 源码/params_schema/best_params
def resolve_strategy(strategy_id, user_id, is_admin=False) -> Optional[Row]:
    # 本人 / admin 返回;他人仅公开策略返回(用于列表/精简详情)
def require_backtest_access(strategy_id, user_id, is_admin=False) -> Row:
    # 仅 owner/admin;他人公开 → StrategyError("BACKTEST_FORBIDDEN");他人私有/不存在 → NO_STRATEGY
def require_live_access(strategy_id, user_id, is_admin=False) -> Tuple[Row, bool]:
    # 返回 (strat, is_follow);owner→(row, False);他人公开→(row, True);他人私有/不存在→NO_STRATEGY
```

### 关键改动点

- `server/services/script_strategy/strategies.py`:
  - `list_strategies`:自己的 + 他人 `is_public=1` 的策略(他人返回 `public_view`);删除 public-derived 分支。
  - `get_strategy`:owner/admin 返回完整(含 script);他人公开返回 `public_view`;他人私有返回 None。
  - `update_strategy`:可更新字段加 `is_public`(仅 owner,已有 owner 校验)。
  - 删除 `_strategy_public_derived`;`_resolve_script` 保留(作者视角解析脚本用)。
- `server/services/script_strategy/batches.py`:
  - `create_backtest_batch` / `list_batches` / `list_batch_tasks` / `retest_batch`:改用 `require_backtest_access`(严格 owner)。
  - `create_live_batch`:改用 `require_live_access`;`is_follow=True` 时用**作者视角脚本**校验 best_params key ⊆ schema(避免私有脚本对跟随者不可见的问题),建 task `user_id=跟随者, strategy_id=作者策略, params=作者 best_params, stock_code=跟随者输入`。

## 4. API 与错误码

- `server/api/script_strategy/schemas.py`:
  - `StrategyOut` 加 `is_public: bool = False`。
  - `StrategyOut.script` 改为 `Optional`(他人公开策略返回精简版,无 script 字段)。
- `server/api/script_strategy/strategies.py`:
  - `backtest`/`batches`/`retest` 端点错误码映射加 `BACKTEST_FORBIDDEN → 403`。
  - `live` 端点:同一端点支持 owner 实盘与黑盒跟随,服务层按 `is_follow` 分流;`LiveRequest` 不变(`stock_code` + `fields`)。
- 隐私原则:他人私有策略在列表/详情/回测/实盘一律 `404 STRATEGY_NOT_FOUND`(不泄漏存在性);他人公开策略的受限操作(回测)返回 `403`,因为用户已在列表看到它。

## 5. 前端

- **ScriptTask.vue**(策略/任务页):
  - 策略列表区分「我的 / 公开」:我的 → 现有操作 + 新增「公开/私有」开关(仅 owner 可见可点);他人公开策略 → 基本卡片 + 「实盘使用」按钮(弹窗输入 stock_code 后调 `/live`),无回测/编辑入口。
  - 由列表返回的 `is_public` + `owner` 判定当前用户视角。
- **ScriptDev.vue**(策略开发页):
  - 他人公开脚本:表单**只读**(禁用编辑/删除/保存按钮),符合 R4"能看到内容但无权修改"。

## 6. 测试

服务层测试(新增于 `tests/server/strategy/test_strategy_v123_service.py` 或独立文件):
- `list_strategies` 显示自己的 + 他人公开策略;他人公开项为精简视图(无 script/best_params)。
- 非 owner 对公开策略 `backtest` → `BACKTEST_FORBIDDEN`;对私有策略 → `NO_STRATEGY`(404)。
- `get_strategy`:他人公开返回精简视图;他人私有返回 None。
- 黑盒跟随:`is_follow=True` 建 task,`user_id=跟随者, params=作者 best_params, stock_code=跟随者输入`。
- 私有脚本 + 公开策略:跟随仍成功(best_params 用作者视角 schema 校验)。
- 公开策略无 best_params 跟随 → `NO_BEST_PARAMS`。
- `update_strategy` 切换 `is_public` 仅 owner 生效。
- 迁移幂等(`test_migration_idempotent` 需兼容新列)。

## 7. 规格文档

`openspec/specs/strategy/spec.md` 补 **REQ-STRAT-019: 策略可见性与权限矩阵(v125, 2026-08-11)**:
- 数据模型:`strategy.is_public`(迁移)。
- 权限矩阵(上表)。
- 黑盒实盘跟随流程与 task 归属。
- 错误码:`403 BACKTEST_FORBIDDEN` / `404 STRATEGY_NOT_FOUND` / `400 NO_BEST_PARAMS`。
- 场景:作者发布公开策略 / 跟随者黑盒实盘 / 非 owner 回测被拒 / 私有策略不可见。

## 8. 范围外(YAGNI)

- 不引入"策略复制/克隆"机制(方案 B 已否决)。
- 不新增独立 follow 端点(方案 C 合并进 `/live`)。
- 不做"跟随关系表"(跟随即建 task 行,`user_id` 天然归属)。
- 不改脚本级 `is_public` 语义(开放源码只读,已符合 R4)。
