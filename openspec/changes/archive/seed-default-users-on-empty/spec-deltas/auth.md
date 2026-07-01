# Spec Delta — seed-default-users-on-empty → auth

## MODIFIED Scenarios

### S-AUTH-001: 新用户首次登录（扩展为同时种 admin + trader）

Given users 表为空（count == 0；可能是首启动 / 开发期 wipe / 全新 DB）
When FastAPI 启动 `on_startup`
Then 自动创建两个默认账号：

| username | password | role | must_change_password |
|---|---|---|---|
| admin | admin123 | admin | true |
| trader | trader123 | trader | true |

And 日志提示首次登录后必须改密码

## ADDED Scenarios

### S-AUTH-006: 开发期 wipe users 表后重启

Given 用户通过 SQLite 工具手动 `DELETE FROM users`（清空 users 表但保留 schema）
When FastAPI 重启
Then `on_startup` 检测到 `count == 0`，自动补 admin 和 trader 两个默认账号
And `[INIT] Created default accounts` 日志出现
And 不影响其他表（orders / trades / positions 等）的数据

## MODIFIED Requirements

### REQ-AUTH 数据模型（注释补充）

`must_change_password: bool, default=True` — 新建用户默认值；admin/trader 默认账号显式置 True 强制首次登录后改密码。