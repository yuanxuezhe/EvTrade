# Tasks: docs/ 与 openspec/ 关系梳理

> 与 [proposal.md](proposal.md) 配套

- [x] **T1** 复核 [docs/specs-history/2026-06-11-spec-p0.md](../../docs/specs-history/2026-06-11-spec-p0.md) 是否真的是 [docs/archive/2026-06-16-initial-analysis.md](../../docs/archive/2026-06-16-initial-analysis.md) 的 override — **通过**：spec-p0.md:5/12 显式声明 `PROJECT_ANALYSIS_REPORT.md` "已过时，本文档为准"，并在 §0 校准说明里逐条 override
- [x] **T2** 全仓搜 `initial-analysis\|PROJECT_ANALYSIS_REPORT` 引用 — **完成**：发现 [docs/specs-history/2026-06-11-spec-p0.md:341](../../docs/specs-history/2026-06-11-spec-p0.md) 仍有一个 DoD todo "更新 PROJECT_ANALYSIS_REPORT.md 完成度表格"，已改为勾选 + 决议说明
- [x] **T3** 删除 [docs/archive/2026-06-16-initial-analysis.md](../../docs/archive/2026-06-16-initial-analysis.md) — **完成**
- [x] **T4** 删除空目录 [docs/archive/](../../docs/archive/) — **完成**
- [x] **T5** 复核 [docs/specs-history/2026-06-22-t0-quick-redesign-v3.md](../../docs/specs-history/2026-06-22-t0-quick-redesign-v3.md) 是否已被对应 OpenSpec change 覆盖 — **保留理由充分**：T0 v1/v2/v3（06-20/21/22）在 openspec 里**无对应 change**，OpenSpec 内的 [t0-exposure-and-aggregate](../../changes/archive/2026-06-19/t0-exposure-and-aggregate/) 是 06-19 的，早于 v1。三份 v* 文件本身就是"OpenSpec 接管前的完整 spec 演进"的范本
- [ ] **T6** 在 [openspec/AGENTS.md](../../openspec/AGENTS.md) 步骤 0 检查清单里追加一行"如需补全静态知识，参考 [docs/](../../docs/) 子目录约定"，明确两套体系的边界
- [ ] **T7** git commit：`docs(structure): archive initial-analysis 已被 spec-p0 override + 明确 docs/openspec 边界`（按 [feedback_commit_granularity](../../.claude/memory/feedback_commit_granularity.md) 拆为单 commit）
- [ ] **T8** 归档此 change 到 [openspec/changes/archive/2026-06-29-docs-vs-openspec-rationalize/](../archive/2026-06-29-docs-vs-openspec-rationalize/)
