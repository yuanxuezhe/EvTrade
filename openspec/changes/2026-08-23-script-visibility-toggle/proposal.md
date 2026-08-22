# Proposal — ScriptDev 脚本编辑增加"公开/私有"开关

## Why

REQ-STRAT-014 已定义脚本 `is_public`（0=私有/1=公开，见 `openspec/specs/strategy/spec.md` REQ-STRAT-014 Scenario「用户共享脚本」），后端（`ScriptCreate/ScriptUpdate/ScriptOut` + `services/script_strategy/scripts.py` 的 list/detail/create/update）与 DB 列均已就绪。**唯一缺口在前端** `ScriptDev.vue`：编辑器表单没有 `is_public` 开关，用户无法在界面上设置脚本私有/公开。KB（`知识库/前端/页面/策略开发与运行.md`）声称已有"公开开关"，代码与文档不一致。

## What Changes

`client/src/views/ScriptDev.vue`（仅前端）：
- `_blankForm()` 增加 `is_public: false`
- `onSelect()` 把 `s.is_public` 拷入 form
- `_formToPayload()` 带上 `is_public`
- 表单加 `el-switch`（公开/私有），`:disabled="isReadonly"`（他人公开脚本只读）

## Backward Compatibility

- 新增字段默认 `false`（私有），与 DB `server_default '0'` 一致；存量脚本不变
- 保存走既有 `createScript/updateScript`，payload 多一个 `is_public` 字段，后端 schema 已支持

## Decisions

| # | 决策点 | 结果 |
|---|---|---|
| Q1 | 开关放哪 | ScriptDev 表单（随保存提交），而非 ScriptTask 式的即时保存——脚本编辑是显式"保存"心智 |
| Q2 | 他人公开脚本 | 开关 `:disabled="isReadonly"`，owner/admin 可改 |

## Reference

- `openspec/specs/strategy/spec.md` REQ-STRAT-014（is_public 数据模型 + 共享脚本场景）
- `知识库/后端服务/策略引擎/脚本策略模块.md`（Script 段）
- `知识库/前端/页面/策略开发与运行.md`（ScriptDev 段）
