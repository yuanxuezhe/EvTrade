# Tasks: Data model knowledge base

- [ ] 1. `openspec/specs/data-model/spec.md` 已创建（含 11 张表 + 字段 + 约束 + 业务规则）✅
- [ ] 2. `server/models/orm.py` 顶部 docstring 加 cross-reference 链接
- [ ] 3. `server/models/orm.py` 每个 class docstring 顶部加「详见 `data-model/spec.md` 第 N 节」
- [ ] 4. `openspec/specs/trading/spec.md` 引用 data-model
- [ ] 5. `openspec/specs/positioning/spec.md` 引用 data-model
- [ ] 6. `openspec/specs/push/spec.md` 引用 data-model
- [ ] 7. `openspec/specs/frontend/spec.md` 引用 data-model
- [ ] 8. `pytest server/ -v` 全绿
- [ ] 9. 提交：`docs(spec): 11 张表结构 knowledge base + 4 cap spec 交叉引用`
- [ ] 10. 归档：spec 不需要 merge（独立 cap），`mv openspec/changes/2026-06-16-data-model-knowledge-base openspec/changes/archive/`
