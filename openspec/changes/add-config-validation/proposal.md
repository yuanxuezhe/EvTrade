# Add config validation at startup

## 1. Why

当前 `server/config.py` 在缺 `JWT_SECRET` 时静默使用 `dev-secret-please-change`，
生产环境一旦未配置就上 JWT，签名密钥可被猜到 → **安全风险**。

同时 hqserver 与 FastAPI 后端的配置分散两处，未共用 Settings 类。

## 2. What

### 2.1 启动校验（必填项缺失即退出）

- `JWT_SECRET` 缺失 → `raise RuntimeError("JWT_SECRET must be set in .env")`
- `EVTRADE_RABBITMQ_URL` 解析失败 → 启动失败
- 端口非法（不是 int） → 启动失败

### 2.2 配置分层

- 引入 `server/config.py` 中的 `Settings` 类继承 `pydantic.BaseSettings`
- 自动从 `server/.env` 加载
- hqserver 继续走自己的 `_env` / `_env_int` 函数（避免循环依赖）

### 2.3 测试

- 加 `server/test_config.py`：单测覆盖 4 个校验分支
- CI 跑 `pytest server/test_config.py hq/test_hqserver.py`

## 3. 影响面

- `server/config.py` — 重构为 Pydantic Settings
- `server/main.py` — 不变（只是 `Settings()` 抛异常被 uvicorn 捕获）
- `server/.env.example` — 标 `<REQUIRED>` 给必填项
- 新增 `server/test_config.py`

## 4. Spec Deltas

`configuration/spec.md`:
- REQ-CFG-004 启动校验：补充 JWT_SECRET 必填 + URL 解析失败
- REQ-CFG-002 增加"必填"列标记

## 5. Tasks

- [ ] 改 `server/config.py` 为 Pydantic BaseSettings
- [ ] 加 `JWT_SECRET` 缺失时 raise
- [ ] 加 `server/test_config.py` 单元测试
- [ ] 更新 `server/.env.example` JWT_SECRET 标 `<REQUIRED>`
- [ ] 更新 `configuration/spec.md`
- [ ] pytest 18/N 变 18/N+M（M = test_config 用例数）
- [ ] commit + push
