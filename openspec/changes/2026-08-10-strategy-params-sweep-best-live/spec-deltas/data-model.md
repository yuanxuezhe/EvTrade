# spec-delta: data-model — strategy_task 表加 3 列 nullable

> 配套 [proposal.md](../proposal.md)

## 改动

`strategy_task` 表加 3 列,全部 nullable,默认 NULL,无破坏性:

| 列名 | 类型 | NULL | 说明 |
|---|---|---|---|
| `sweep_id` | VARCHAR(32) | YES | 同一 sweep 多 task 共享,summary task 也带 (用 `sweep_total=1` 区分) |
| `sweep_metric` | VARCHAR(32) | YES | 排序指标名 sharpe / total_return / calmar |
| `sweep_total` | INT | YES | 同 sweep 的 task 总数 (冗余但查快;前端直接拿不用 COUNT) |

## 兼容性

- **旧 task 行**:`sweep_id`/`sweep_metric`/`sweep_total` 全 NULL → 前端按 `sweep_id IS NULL` 判断 "单次回测"
- **不需回填**:旧 task 没 sweep 概念,NULL 是正确语义
- **不需 alembic 数据迁移**:仅 DDL,无 DML

## 索引 (可选)

未来若按 sweep_id 查多 task,可加:
```sql
ALTER TABLE strategy_task ADD INDEX idx_sweep_id (sweep_id);
```

本 change 不加(等真有人按 sweep_id 频繁查再加)。

## 影响

- `server/tables/strategy_task.py` 类定义补 3 个字段
- `strategy_exec/data_access/strategy_task.py` 增删改函数可选支持 sweep_id (透传即可,无业务逻辑改动)
- 前端 ScriptTask.vue 渲染时:NULL → "单次回测";非 NULL → "扫描 (N 组)"