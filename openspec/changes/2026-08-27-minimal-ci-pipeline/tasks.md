# Tasks: minimal-ci-pipeline (2026-08-27)

> 单 commit：仅加 CI 配置，不动业务代码。

## Commit 拆解

- [ ] **commit 1**: `ci(evtrade): 加 GitHub Actions pytest + schema drift workflow (P1-2)`
  - 新增 `.github/workflows/ci.yml`（pytest + schema drift 双 job）
  - 可选：`.github/workflows/schema-drift-cron.yml`（周一早上跑一次）

## 验证

- [ ] YAML 合法（用 `act` 或 GitHub web 校验）
- [ ] pytest 装 MySQL 容器跑测试通过
- [ ] schema-drift 检测到 drift 时 exit 1
- [ ] 触发条件：push to master + PR + workflow_dispatch