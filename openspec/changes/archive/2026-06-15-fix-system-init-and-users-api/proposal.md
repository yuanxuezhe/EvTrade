# Fix SystemInit & Users API Contract Bugs

## Why

v4 实施期间 `SystemInit.vue` 和 `Users.vue` 的后端契约被破坏 (代码 review 漏看)，
到 v5 验证时才发现。用户报告"系统初始化 / 用户管理 控制台报错" 5 个 bug 需修复：

| # | 位置 | Bug | 修复 |
|---|------|-----|------|
| 1 | client/src/api/admin.js | `t...[truncated]