# 启动时种入默认 admin + trader

## 1. Why

2026-06-22 用户报：数据库里有 `trader1` 但**没有** `admin`，
`admin/admin123` 无法登录（401）。

当前 `server/main.py:43-66` 的 `on_startup`：

```python
count = db.query(User).count()
if count == 0:   # ← 只在 users 表完全空时才种
    admin = User(username="admin", password_hash=hash_password("admin123"), ...)
```

只在"完全空 DB"时才创建 admin。一旦有任何用户存在（哪怕是
测试时建的 `trader1`），admin 就再也不会被自动补上。

`openspec/specs/auth/spec.md:55` (S-AUTH-001) 写的是
"Given 系统中无用户, When FastAPI 启动, Then 自动创建 admin/admin123"
—— 当前实现 ≠ spec 意图。spec 应是"无用户时同时提供 admin + trader 两个默认账号"，
覆盖"首启动"和"开发期手动清表"两个场景。

## 2. What

### 2.1 默认账号种子（启动时自动）

`server/main.py::on_startup` 当 `count == 0` 时，同时插入：

| username | password | role | full_name | is_active | must_change_password |
|---|---|---|---|---|---|
| admin | admin123 | admin | 系统管理员 | True | True |
| trader | trader123 | trader | 默认交易员 | True | True |

两次 `db.add()` + 单次 `db.commit()`（保持原子）。
日志改为：

```
[INIT] Created default accounts (users table was empty):
  - admin / admin123 (role=admin)
  - trader / trader123 (role=trader)
[INIT] Please change the password after first login.
```

### 2.2 spec 同步

- `openspec/specs/auth/spec.md` S-AUTH-001 改写：同时种 admin 和 trader
- 新增 S-AUTH-006 "开发期 wipe 后重启"：Given users 表被清空, When 启动, Then 自动补两个账号

### 2.3 当前 DB 现场补救

用户当前 DB 里只有 `trader1`（无 admin）。本次同步手工 insert 一行
`admin/admin123`（`must_change_password=True`），让用户**立刻**能登录。
`trader1` 保留不动。

## 3. 影响面

- `server/main.py` — `on_startup` 内部扩展（不改签名/外部行为）
- `server/evtrade.db` — 当前现场补 1 行 admin；后续若 wipe 表，启动时自动补 2 行
- `openspec/specs/auth/spec.md` — S-AUTH-001 改写 + 新增 S-AUTH-006

## 4. Spec Deltas

详见 `spec-deltas/auth.md`：
- MODIFIED: S-AUTH-001 措辞
- ADDED: S-AUTH-006（wipe 后自动补）
- MODIFIED: REQ-AUTH 数据模型字段注释补 `must_change_password` 默认值约定

## 5. 不在本 change 范围

- 升级 bcrypt rounds（仍用 12）
- 增加 `viewer/viewer123` 默认账号（用户未要求）
- 引入 CLI `python scripts/seed_users.py` 显式调用入口（用户选了"自动触发"路径）
- `client/src/views/Login.vue` 提示信息（无 spec 要求）

## 6. 归档条件

- [ ] `python scripts/evctl.py restart` → 三服务起，`/api/health` 200
- [ ] `curl /api/auth/login -d 'username=admin&password=admin123'` → 200 + JWT
- [ ] `curl /api/auth/login -d 'username=trader&password=trader123'` → 200 + JWT（仅在 wipe 后才能触发；当前 DB 有 trader1，所以必须先手动 wipe users 表才能验）
- [ ] pytest 全绿