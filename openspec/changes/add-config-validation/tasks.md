# Tasks — add-config-validation

## 实施步骤

- [ ] 1. 读 `server/config.py` 当前实现，识别所有 os.environ.get 调用
- [ ] 2. 重构为 Pydantic `BaseSettings`，保留旧 key 名以兼容 .env
- [ ] 3. JWT_SECRET 缺失 → raise RuntimeError
- [ ] 4. URL 解析 → 用 `pydantic.HttpUrl`
- [ ] 5. 写 `server/test_config.py`：
  - [ ] 缺 JWT_SECRET → raise
  - [ ] 缺 RabbitMQ URL → 用默认
  - [ ] URL 拼错 → 校验失败
  - [ ] 端口非数字 → 校验失败
- [ ] 6. 更新 `server/.env.example` JWT_SECRET 注释为 `<REQUIRED>`
- [ ] 7. 更新 `openspec/specs/configuration/spec.md`（REQ-CFG-004 + REQ-CFG-002）
- [ ] 8. `pytest server/test_config.py hq/test_hqserver.py` 全绿
- [ ] 9. commit: `feat(config): JWT_SECRET 必填 + Pydantic Settings 校验`
- [ ] 10. push origin master

## 验证

- [ ] `pytest` 全绿
- [ ] 删 `JWT_SECRET=` 那一行后启动 FastAPI → 看到明确错误信息并退出
- [ ] `git log --oneline -1` 显示新 commit
