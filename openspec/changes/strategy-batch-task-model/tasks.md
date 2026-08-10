# tasks — strategy-batch-task-model 实施清单

> 依据 [design.md](design.md) 与 specs deltas 拆解。按依赖排序：迁移 → 后端 → strategy_exec → 前端 → 测试。

## 1. 序号表泛化（多生成器）

- [ ] 1.1 `order_no_seq` 表改结构：加 `seq_name` PK，现有行 `seq_name='order_no'`；新增 `task_batch` 行（迁移脚本，幂等）
- [ ] 1.2 `server/services/order_no.py` 抽 `next_seq(db, name)`（原子 UPSERT +1），`next_order_no` 改为 `next_seq(db, 'order_no')`，行为不变
- [ ] 1.3 `server/tables/order_no_seq.py` 重新生成（tables-codegen）对齐新结构

## 2. `strategy` 表 + `strategy_task` 重构（迁移）

- [ ] 2.1 建 `strategy` 表（strategy_id 自增 PK / user_id / script_id / name / status / best_params JSON NULL / 时间戳，索引 (user_id, script_id)）
- [ ] 2.2 `strategy_task` 加 `strategy_id` + `batch_no`；回填：每个 task 按 script_id 映射到策略（先为每个 strategy_script 建同名 strategy 再映射）
- [ ] 2.3 `strategy_task` 删 `script_id` / `best_params` / `sweep_id` / `sweep_total` / `sweep_metric` 列
- [ ] 2.4 `server/tables/strategy.py` 新增（tables-codegen）+ `server/tables/strategy_task.py` 重新生成
- [ ] 2.5 `server/schema.yml` 与 `server/models/orm.py` 同步（diff 0 除注释）

## 3. 后端 API（策略 CRUD + 批次 + 实盘门禁）

- [ ] 3.1 `server/api/script_strategy/endpoints.py`：新增 strategies 子资源 CRUD（`POST /strategies {name, script_id}` 不填参数/不定模式）
- [ ] 3.2 `POST /strategies/{id}/backtest`：单次=1 行 task / 扫描=按 param_ranges 展开 N 行 task，生成 batch（next_seq task_batch）+ 转发 strategy_exec
- [ ] 3.3 `GET /strategies/{id}/batches` + `GET /strategies/{id}/batches/{batch_no}/tasks`：批次聚合 + 任务表格数据（参数列 + 结果列）
- [ ] 3.4 `POST /strategies/{id}/live`：校验 `best_params` 非空（否则 400 `NO_BEST_PARAMS`），用 best_params 建 1 行 live task（新 batch_no）并转发
- [ ] 3.5 `GET /tasks/{id}` 详情/`stop`/`DELETE` 改挂 strategy 语义（脚本字段经 strategy→script 解析）

## 4. strategy_exec 引擎适配

- [ ] 4.1 `data_access/strategy_task.py`：run-task 请求体带 `strategy_id`，落库写 `strategy_id`
- [ ] 4.2 `api/internal.py` `run-sweep-task`：请求体改 `param_ranges`（int/float 起止+步长含端点 / choice 值列表 / string 固定）+ `batch_no`
- [ ] 4.3 `engines/backtrader/sweep.py`：按 param_ranges 类型化展开组合 → 笛卡尔积（软 64 / 硬 512）；批次内 tasks 共享 batch_no；并发 Semaphore；失败容错
- [ ] 4.4 批次完成后：按 batch 内 finished tasks 以 metric 排序取 top1 → `UPDATE strategy SET best_params`（全部失败不写）
- [ ] 4.5 移除 summary task / sweep_summary 逻辑；`backtest_result` 不再需要 sweep_results 顶层冗余

## 5. 前端 ScriptTask 批次/任务两段式 UI

- [ ] 5.1 ScriptTask.vue：顶部策略选择/新建（{name, script_id}），去掉建任务时填 params 的入口
- [ ] 5.2 单次回测表单：全部参数按 `params_schema` 类型渲染，默认值=default
- [ ] 5.3 参数扫描表单：int/float → 起止+步长（默认带出 min/max/step）；choice → 逗号分隔值列表；string → 固定值；提交生成批次
- [ ] 5.4 批次列表（batch_no/时间/mode/task_count/best）+ 批次内任务表格（前几列参数动态列、后几列结果）
- [ ] 5.5 点击任务行 → 下方详情（backtest_result 图表/信号/audit）
- [ ] 5.6 实盘启动：best_params 为空提示"请先回测生成最优参数"并阻止；成功后显示"实盘"徽章
- [ ] 5.7 `client/src/api/script_strategy.js` 对齐新端点（strategies/batches/backtest/live）
- [ ] 5.8 订阅 ws `task_progress_update` 实时刷新批次内任务进度

## 6. 测试与回归

- [ ] 6.1 迁移脚本幂等自测（dev 重建 DB + 存量 task→strategy 映射验证）
- [ ] 6.2 后端单测：策略 CRUD、批次生成、best 覆盖、实盘门禁（NO_BEST_PARAMS）
- [ ] 6.3 strategy_exec 单测：param_ranges 展开（含端点）、16 组合、部分失败回写 best、全失败不写、grid>512 拒绝
- [ ] 6.4 前端：批次表格动态列、类型化扫描表单、实盘徽章、门禁提示
- [ ] 6.5 回归：现有单次回测行为不变（`mode=backtest` 1 行 task 可跑可查）；`next_order_no` 委托序号行为不变
