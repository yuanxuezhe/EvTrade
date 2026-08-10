# design.md — 注入机制 / sweep 引擎 / 数据流

## 1. Schema 注入机制 (Phase 2)

### 流程图

```
┌─────────────────┐    ┌──────────────────────┐    ┌─────────────────────┐
│ strategy_script │ → │ load_strategy_class  │ → │ _inject_params_from │
│  - code         │   │  (sandbox exec)      │    │  _schema(cls, sch)  │
│  - params_schema│   │  返用户定义的类      │    │  覆盖 cls.params    │
└─────────────────┘    └──────────────────────┘    └─────────────────────┘
                                                              │
                                                              ↓
                                                ┌─────────────────────────┐
                                                │ cerebro.addstrategy(cls,│
                                                │   fast=7, slow=30, ...)  │
                                                │ backtrader 把 kwargs 注入│
                                                │ cls.p.x (backtrader原生) │
                                                └─────────────────────────┘
```

### `_inject_params_from_schema` 算法

```python
# 伪代码,实际位置: strategy_exec/sandbox/loader.py

from typing import Type, List, Dict, Any
import ast

def _extract_declared_keys(cls: Type) -> set:
[str]:
    """AST 扫 cls.params 取 key 集合 (静态,不实例化)"""
    try:
        # cls 定义时的源码 — 取 params 赋值的 RHS
        source = getattr(cls, '__source__', None) or ast.unparse(ast.parse(...))
        tree = ast.parse(source)
        # 找 class 定义 + 其 params 赋值
        ...
    except Exception:
        return set()

def _inject_params_from_schema(cls: Type, params_schema: List[Dict[str, Any]]) -> Type:
    """以 schema 为准,覆盖 cls.params (strict fail-fast 不一致 raise)

    决策 #1: strict 模式 — schema ∩ code 不一致 → ValueError
    """
    if not params_schema:
        return cls  # schema 空 = 用户脚本无 params,保持原状

    declared = _extract_declared_keys(cls)
    schema_keys = {p["key"] for p in params_schema}

    if declared != schema_keys:
        only_code = declared - schema_keys
        only_schema = schema_keys - declared
        raise ValueError(
            f"策略类声明的 params 与 schema 不一致 (strict mode):\n"
            f"  code 多出: {only_code or '(无)'}\n"
            f"  schema 多出: {only_schema or '(无)'}\n"
            f"  v_next+: 请删掉代码里的 params = (...)\n"
            f"           schema 是唯一契约, 由前端 ScriptDev 编辑"
        )

    # 覆盖 cls.params — backtrader 元类 next time 会读 cls.params 装到 self.p
    cls.params = tuple((p["key"], p["default"]) for p in params_schema)
    return cls
```

**关键点**:
- `_extract_declared_keys` 用 AST 静态扫,不需要实例化类(实例化会触发指标计算,慢)
- `declared` 和 `schema_keys` 比较,**顺序不重要**(都是 set)
- 覆盖 `cls.params` 后 backtrader 元类立刻读到新值,无需重新定义类
- `params_schema=None` (旧调用) → 老逻辑,不注入,完美 backward compat

## 2. Sweep 引擎 (Phase 4)

### 数据流

```
POST /api/strategy/tasks/{id}/run-sweep
   {
     param_grid: { fast: [3,5,7,10], slow: [15,20,30,60] },
     metric: "sharpe",
     select_top_n: 1
   }
                ↓ EvTrade 转发
POST /internal/run-sweep-task (strategy_exec)
                ↓
run_sweep():
  1. iter_param_grid({fast:[3,5,7,10], slow:[15,20,30,60]})
     → 16 个 dict 组合
  2. sweep_id = uuid.uuid4().hex[:32]
  3. asyncio.Semaphore(2) 并发跑:
     for params in grid:
        await sem:
           task_id = create_sweep_task(user_id, script_id, params, sweep_id, metric)
           status = run_backtest(task_id, params=params, ...)
           update_task_status(task_id, 'finished', best_params=params, ...)
           record metric_value (SharpeRatio analyzer 取)
  4. 全部完成 → create summary task:
     summary_task_id = create_task(...)
     update_sweep_summary(summary_task_id, sweep_results, best_params=top1)
                ↓
   返 { summary_task_id, sweep_id, total_runs: 16, best_params: {...} }
```

### 关键并发控制

- `asyncio.Semaphore(N)` 限制同时跑的 backtest 数
- 每个组合 = 独立 `strategy_task` row (PK 不同,不撞乐观锁)
- 失败单组合 → 记 status='failed',sweep 继续 (决策 #5: 容错)
- sweep_id 共享 → 前端按 sweep_id 聚合查

### 数据表 schema (3 列 nullable)

```sql
-- server/migrations/2026-08-11-add-strategy-sweep-fields.py
ALTER TABLE strategy_task
  ADD COLUMN sweep_id VARCHAR(32) NULL COMMENT '同一 sweep 多 task 共享, summary task 也带 (标 is_summary=1)',
  ADD COLUMN sweep_metric VARCHAR(32) NULL COMMENT '排序指标名 sharpe/total_return/calmar',
  ADD COLUMN sweep_total INT NULL COMMENT '同 sweep 的 task 数 (冗余但查快)';

-- summary task 额外用 existing fields:
-- params = null (无单组 params)
-- best_params = top1 params dict
-- backtest_result = {sweep_results: [...], metric: "sharpe", total_runs: 16}
```

## 3. 数据流 (端到端)

```
┌─────────────┐                  ┌──────────────────┐
│ ScriptDev   │ ──save script──→ │ strategy_script  │
│ (编辑schema)│                  │ code + schema    │
└─────────────┘                  └──────────────────┘
                                          │
                                          │ loader inject
                                          ↓
┌─────────────┐  run-sweep         ┌──────────────────┐
│ ScriptTask  │ ──(param_grid)───→ │ strategy_exec    │
│             │                    │ sweep engine     │
│             │                    │ ↓                │
│             │                    │ strategy_task ×N │
│             │                    │  (sweep_id, ...) │
└─────────────┘                    └──────────────────┘
                                          │ best_params
                                          ↓
                                   ┌──────────────────┐
                                   │ summary task     │
                                   │ best_params:     │
                                   │  {fast:7,slow:30}│
                                   └──────────────────┘
                                          │ 手动选 (决策 #5)
                                          ↓
┌─────────────┐  启 live            ┌──────────────────┐
│ ScriptTask  │ ──(best_params)──→ │ strategy_exec    │
│ 启实盘表单  │                    │ live engine      │
└─────────────┘                    └──────────────────┘
```

## 4. 前端 UI 关键交互

### Sweep 启动表单

```
┌─────────────────────────────────────────────────────────────┐
│ 参数扫描 (sweep) — mas_v1                                    │
├─────────────────────────────────────────────────────────────┤
│ 标的代码: [000001.SZ]   区间: [20250101] ~ [20260701]        │
│ 排序指标: (•) sharpe ( ) total_return ( ) calmar           │
├─────────────────────────────────────────────────────────────┤
│ 参数        扫描值        锁定(不参与)                       │
│ fast       [3,5,7,10]    [ ]                                │
│ slow       [15,20,30,60] [ ]                                │
│ qty        [100]         [x]  ← 默认锁定(只 1 个值)         │
│ rsi_period [14]         [x]  ← 默认锁定                      │
├─────────────────────────────────────────────────────────────┤
│ 预计组合数: 16 (4 × 4)   预估耗时: ~5min                    │
│ ⚠️ > 64 警告   ⛔ > 512 拒绝                                │
│ [开始扫描]                                                  │
└─────────────────────────────────────────────────────────────┘
```

### 实盘启动 — "从历史回测选参数"

```
┌─────────────────────────────────────────────────────────────┐
│ 启动实盘任务                                                │
├─────────────────────────────────────────────────────────────┤
│ 选择脚本: [mas_v1 ▼]  标的: [000001.SZ]                     │
│ 参数来源: ( ) 默认值 (from schema)                          │
│           (•) 从历史回测选择 [选...]  ┌───────────────┐    │
│           ( ) 手动指定                │ mas_v1 历史回测│    │
│                                       │  ┌───────────┐ │    │
│                                       │  │#43 sweep  │ │    │
│                                       │  │16 runs    │ │    │
│                                       │  │sharpe 1.82│ │    │
│                                       │  │fast=7     │ │    │
│                                       │  │slow=30    │ │    │
│                                       │  ├───────────┤ │    │
│                                       │  │#42 single │ │    │
│                                       │  │sharpe 1.21│ │    │
│                                       │  ├───────────┤ │    │
│                                       │  │...        │ │    │
│                                       │  └───────────┘ │    │
│                                       │  [取消]  [确认]│    │
│                                       └───────────────┘    │
├─────────────────────────────────────────────────────────────┤
│ 参数预览:                                                   │
│   fast = 7                                                 │
│   slow = 30                                                │
│   qty = 100                                                │
│   rsi_period = 14                                          │
│ [开始实盘]                                                  │
└─────────────────────────────────────────────────────────────┘
```

## 5. 边界场景处理

| 场景 | 行为 |
|---|---|
| Sweep 中某组合 run 抛错 | 该 task status='failed',其它继续;sweep_results 标 'failed',best 仍从成功的挑 |
| Sweep 全失败 | summary task status='failed',best_params=null,UI 提示 |
| Sweep 中途 strategy_exec 重启 | 已持久化到 DB 的 task 留 'pending' 或 'running';重启后无 resume 机制 → 单独 change (out of scope);本 change 至少 task 记录不丢 |
| best_params 引用了已删字段 (schema 变了) | live 启时校验 task.params key ⊆ 当前 schema,缺失 → 警告 + 阻断启动 |
| schema 字段全 lock (0 组合) | UI 校验 → 拒绝提交,提示"至少解锁 1 个参数" |
| 单 run + sweep 混用 | 单 run 字段全 NULL,前端 `sweep_id IS NULL` 区分 |
| sweep_id 重复 (极端) | uuid4 hex32 撞概率 ~0,DB 不强约束,撞了就当新 sweep (业务无影响) |