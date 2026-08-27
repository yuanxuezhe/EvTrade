# P1-2: 最小 CI（GitHub Actions pytest + schema drift）

> 用户拍板 2026-08-27：P1 系列的第 2 子项（半天）。
> Why：pytest 基线已达 58/58/0，但要防止未来回归 + schema 漂移没人发现。

## Why

当前 EvTrade 项目无 CI：
- 改 base.py / schema.yml 后无自动校验
- 跑 `pytest` 全靠本地手动
- schema drift（dev 改 vs prod 不一致）只能依赖人肉 `sync_schema.py diff`

## What

**1 commit**（按 v6 规范：单 commit 单目的 = 加 CI）

### 改动 1：`.github/workflows/ci.yml`（新增文件）

- **触发**：push to master + PR to master
- **jobs**：
  1. **pytest**（~3 min）：
     - 装依赖：`uv sync` 或 `pip install -r requirements.txt`
     - 起 MySQL 容器（service）
     - 跑 `pytest server/tests/ tests/ --tb=short -q`
     - 限制：fixture 不删表，但 CI 用 fresh DB 容器，无生产数据风险
  2. **schema-drift**（~30s）：
     - 跑 `python scripts/sync_schema.py diff`
     - 任何 drift 报告退出非零

### 改动 2：`.github/workflows/schema-drift.yml`（可选）

- 周一早上 cron 跑一次完整 sync_schema.py export/diff
- 把 dev/prod 漂移发到 #dev-alerts Slack webhook（暂不实现，留作 P1-2.1）

### 改动 3：`pytest.ini` 或 `conftest.py`（如有需要）

- 标记 `slow` 集成测试 → CI 跳过（避免 5min 超时）
- 标记 `requires_broker` → CI 跳过（broker 容器不在 CI 跑）

## 不做什么

- **不动** 任何业务代码（仅加 CI 配置文件）
- **不动** 数据库 schema
- **不动** 已有 `pytest` 行为
- **不在** 第一次 commit 加 Slack webhook（避免引入 secret 管理）

## 验证 (v6 完成自查)

- [ ] `.github/workflows/ci.yml` YAML 语法合法（用 `act` 或 web 在线校验）
- [ ] 触发条件正确（push + PR + workflow_dispatch）
- [ ] pytest job 装 MySQL 容器、跑 `pytest server/tests/ tests/ --tb=short -q`
- [ ] schema-drift job 调 `sync_schema.py diff`，diff 时 exit 1
- [ ] CI 文档短（< 80 行），其他写到 README.md 引用

## 数据安全（用户硬规则 2026-08-27）

CI 用 fresh MySQL 容器，**不连生产 DB**。fixture DELETE 不影响生产（容器销毁即清）。