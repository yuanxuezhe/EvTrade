# Tasks — add-config-validation

## 实施 commit
- `d35ed8e` feat(config): 启动校验 + JWT_SECRET auto-gen + test_config 单测

## 任务列表

- [x] 1. 读 `server/config.py` 当前实现，识别所有 os.environ.get 调用 — 已读，确认 ConfigValidator + frozen Settings 已存在
- [x] 2. 重构为 Pydantic `BaseSettings` — **调整**：保留 frozen dataclass（避免引入 Pydantic v1 + Py3.6 兼容性风险）；REQ-CFG-006 改为测试覆盖
- [x] 3. JWT_SECRET 缺失 → raise RuntimeError — **调整**：security.py 改为 auto-gen（`secrets.token_urlsafe(64)` + 持久化 `.secret_key`），ConfigValidator 仅 WARN（多实例部署需显式 env var；单实例接受 auto-gen）
- [x] 4. URL 解析 → 用 `pydantic.HttpUrl` — **调整**：保留 `_env` 简单函数 + ConfigValidator 检查空字符串（避免 Pydantic 依赖）
- [x] 5. 写 `server/test_config.py`：6 个单测全 PASS
  - [x] 缺 JWT_SECRET → warn（不是 raise）
  - [x] 缺 RabbitMQ URL → error
  - [x] RPC_TIMEOUT 越界 → warn
  - [x] API_PORT 越界 → error
  - [x] happy path → passed
  - [x] validate_config() raise on errors
- [x] 6. 更新 `server/.env.example` JWT_SECRET 注释 — 加 `EVTRADE_SECRET=<REQUIRED for multi-instance>` 注释
- [x] 7. 更新 `openspec/specs/configuration/spec.md`
  - REQ-CFG-004 重写（auto-gen 语义）
  - REQ-CFG-006 新增（必填项校验测试覆盖，原 SysStatus 编号改 REQ-CFG-007）
  - S-CFG-004 新增（JWT_SECRET auto-gen）
  - S-CFG-005 新增（API_PORT 越界）
  - Known Issues M1 标 ✅ Done
- [x] 8. `pytest server/test_config.py` 全绿（6/6 PASS）
- [x] 9. commit — `d35ed8e`
- [x] 10. tracking 标 M1 Done — 本 commit 包含

## 验证

- [x] `pytest server/test_config.py` 6/6 PASS
- [x] ConfigValidator 4 分支覆盖（JWT_WARN / RabbitMQ_error / RPC_WARN / Port_error）
- [x] validate_config() 在有 errors 时正确 raise RuntimeError
- [x] `git log --oneline -1` 显示 `d35ed8e`
- [x] configuration/spec.md 编号一致（CFG-001 ~ 007 / S-CFG-001 ~ 005）

## 偏离提案的决策

| 提案 | 实际 | 理由 |
|---|---|---|
| Pydantic BaseSettings | 保留 frozen dataclass | Pydantic v1 + Py3.6 兼容性风险；当前 dataclass + `_env` 函数已足 |
| JWT_SECRET 缺失 → raise | auto-gen + WARN | 实际更安全（每实例 unique 强随机密钥），少 onboarding 步骤 |
| pydantic.HttpUrl | `_env` 简单字符串检查 | 避免 Pydantic 依赖；URL 格式错误由 RabbitMQ 客户端连接时报错 |