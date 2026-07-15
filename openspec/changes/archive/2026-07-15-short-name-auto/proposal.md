# Proposal: short_name 自动生成 + ST 前缀保留 (v46+ short-name-auto)

> **作者**: Hermes (root 环境, 绕过 Claude Code v15 root 拒绝)
> **日期**: 2026-07-15
> **spec-id**: REQ-STOCK-007 + REQ-FE-STOCK-HIDE
> **关联 spec**: `openspec/specs/stocks/spec.md` §REQ-STOCK-006 + `openspec/specs/frontend/spec.md` §REQ-FE-STOCK-CREATE
> **依赖**: v25 stocks-cache-and-short-name (short_name 字段已存在 + v25 已 backfill)、v46 stock-info-create (POST /api/stocks)

---

## 背景 (Why)

v25 引入了 `short_name` 字段（拼音首字母简称），v46 让 admin 可以在 UI 手动添加股票。但当前实现有两个问题：

1. **生成规则不完善**：现有 `to_short_name()` 函数（`server/scripts/backfill_short_name.py:60`）用 `pypinyin.lazy_pinyin` 直接转换整个 stock_name，对 ST 股处理错误：
   - `ST华微` → `SHW`（把 S、T 当成拼音首字母，丢掉了 ST 前缀语义）
   - `*ST实达` → `*SD`（同上，`*` 被保留，但 ST 段丢失）
   - 用户期望：`ST华微` → `STHW`，`*ST实达` → `*STSD`

2. **admin 添加体验差**：v46 让 admin 在添加对话框手填 short_name，但：
   - short_name 应该由 stock_name 自动派生（用户输入中文名后无需手填）
   - 编辑对话框同样应该不显示 short_name 字段（避免误改）
   - 表格"首字母"列对 admin 决策没有价值（用户希望隐藏）

## 目标 (What)

1. **后端**：所有路径自动生成 short_name，admin 不需要也不允许手填
   - `POST /api/stocks` 时根据 stock_name 自动算 short_name
   - `PATCH /api/stocks/{code}` 时如果改了 stock_name，重新算 short_name
   - ST 前缀（`*ST` / `ST`，大小写不敏感）保留到 short_name 开头

2. **前端**：完全隐藏 short_name 用户编辑界面
   - 表格删"首字母"列
   - 添加对话框删 short_name input
   - 编辑对话框删 short_name input

3. **OpenSpec**：明确写出 REQ-STOCK-007（自动生成规则）+ REQ-FE-STOCK-HIDE（前端隐藏）

## 非目标 (Non-Goals)

- ❌ 不跑全表 backfill 重算 5532 条存量 short_name（保留现状，存量如果有 `SHW` 错误的也保留）
- ❌ 不改 ST 股行情 / 交易 / 推送相关逻辑
- ❌ 不改 backfill 脚本本身的行为（仅重构引用，保持脚本独立可用）

## 影响面 (Impact)

| 模块 | 改动 | 风险 |
|---|---|---|
| `server/services/short_name.py` | **新建**（独立模块，导出 to_short_name） | 低（新建） |
| `server/scripts/backfill_short_name.py` | 改 import + 删除本地副本函数 | 低（脚本功能不变） |
| `server/api/stocks.py` | Pydantic 删 short_name 字段 + docstring | 中（破坏 v46 API 契约） |
| `server/repo/stocks.py` | create_by_admin 自动算 + update_by_admin 检测 stock_name 改动 | 中（语义变化） |
| `client/src/views/AdminStockConfig.vue` | 删 6 处 short_name 引用 + 隐藏"首字母"列 | 中（破坏 v46 前端 UI） |
| `openspec/specs/stocks/spec.md` | 加 REQ-STOCK-007 | 低 |
| `openspec/specs/frontend/spec.md` | 加 REQ-FE-STOCK-HIDE | 低 |
