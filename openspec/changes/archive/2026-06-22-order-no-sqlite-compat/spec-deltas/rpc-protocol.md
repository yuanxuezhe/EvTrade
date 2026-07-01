# spec-delta: rpc-protocol

## REQ-RPC-009.1 修订

**原文本**（`openspec/specs/rpc-protocol/spec.md:82`）：
> REQ-RPC-009.1: 单语句原子自增, 使用 SQLite ≥ 3.35 `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` 模式

**新文本**：
> REQ-RPC-009.1: 序号生成须保证 8 位唯一、原子自增、持久化、跨进程安全。具体实现允许两条路径：
>   (a) 理想方案：SQLite ≥ 3.35 单语句 `INSERT ... ON CONFLICT DO UPDATE ... RETURNING`（1 步）
>   (b) 兼容方案：SQLite ≥ 3.21 三步分离 `INSERT OR IGNORE` + `UPDATE` + `SELECT`，配合函数内 commit（3 步）
>
> 当前生产环境 Python 3.6.8 自带 SQLite 3.21.0，使用兼容方案 (b)。
> 切换到方案 (a) 需先升级 Python 到 ≥ 3.7（自带 SQLite ≥ 3.21，部分 3.7+ 自带 3.30+）或 ≥ 3.9（自带 3.32+），或换用更高版本的 libsqlite3。

## 勘误历史

- 2026-06-22 修订：原方案假设 SQLite 3.50.4 与实际 3.21.0 不符，降级为兼容方案
