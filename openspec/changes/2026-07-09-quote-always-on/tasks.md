# Tasks

## 1. proposal/spec/tasks 三件套（已完成）
- [x] 1.1 `proposal.md`
- [x] 1.2 `spec-deltas/configuration.md`
- [x] 1.3 `spec-deltas/frontend.md`
- [x] 1.4 `tasks.md`

## 2. 代码改动
- [ ] 2.1 `server/main.py:124-128` 删 `if not settings.STRATEGY_ENGINE_ENABLED: ... return` 守卫，仅保留 pytest 守门 + try/except
- [ ] 2.2 `server/services/strategy/quote_consumer.py:11` docstring 移除 STRATEGY_ENGINE_ENABLED 守门描述

## 3. spec 同步
- [ ] 3.1 找到 `openspec/specs/configuration/spec.md` 中 REQ-CFG-008 段，改 Scenario 措辞
- [ ] 3.2 在 `openspec/specs/frontend/spec.md` Requirements 末尾前插入 REQ-FE-520

## 4. 验证
- [ ] 4.1 backend 重启看 `[INIT]` 日志不再有 "STRATEGY_ENGINE_ENABLED=false" 分支
- [ ] 4.2 backend.log 出现 `quote_consumer connected` → `[quote_consumer health] engines=0 ticks_total>0`
- [ ] 4.3 30s 内开始累计 ticks_total > 0
- [ ] 4.4 保留 `STRATEGY_ENGINE_ENABLED=1`,确认 strategy endpoints.py 守门仍有效

## 5. 提交归档
- [ ] 5.1 `git commit -m "feat(server): QuoteConsumer 7×24 启用,解耦 STRATEGY_ENGINE_ENABLED 守门"` 单文件 +1/-1
- [ ] 5.2 `openspec archive 2026-07-09-quote-always-on`
- [ ] 5.3 第二个 commit 同步 spec 到 `openspec/specs/`
