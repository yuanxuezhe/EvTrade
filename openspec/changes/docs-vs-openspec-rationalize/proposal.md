# docs/ 与 openspec/ 目录关系梳理

> 创建日期：2026-06-29
> 状态：draft
> 决策：保留两个目录，明确各自角色，清理 [docs/](docs/) 里的历史遗留

## Why

用户观察到 [docs/](../docs/) 和 [openspec/](../openspec/) 都有"文档"，感觉重复，担心分工不清。

经过核查：

- **openspec/** 是**带状态的活工作流**：`.openspec.yaml` + `config.yaml` + `AGENTS.md` + `changes/` + `specs/`，配套有 6 个 `openspec-*` skill。`specs/` 是**当前真相源**，`changes/` 是**变更追踪**。
- **docs/** 是**静态归档/参考**：无任何工具配置，openspec 工作流里**没有反向引用** docs/，完全是独立沉淀。

二者不是"重复"，是"工作流 vs 沉淀"的不同角色。直接合并会破坏 OpenSpec 工作流约定（`changes/archive/<date>-<name>` 路径、spec 同步流程、`.openspec.yaml` 工具配置），且会丢失活工作流与死文档的语义差异。

## What 做什么

不合并目录。明确边界，并对 [docs/](../docs/) 做一次清理：

### docs/ 子目录处置

| 子目录 | 处置 | 理由 |
|---|---|---|
| [docs/archive/2026-06-16-initial-analysis.md](../docs/archive/2026-06-16-initial-analysis.md) | **废弃（删除）** | 是早期子代理生成的初始分析报告，自身标注"子代理早期生成"，且已被 [docs/specs-history/2026-06-11-spec-p0.md](../docs/specs-history/2026-06-11-spec-p0.md) 显式 override（"🔴 高优先级报告里的未实现项"已被 v1 重写）。P0 spec 才是真相源。 |
| [docs/specs-history/](../docs/specs-history/)（4 个文件） | **保留** | 命名带 `-history`，功能上是"被覆盖前"的 spec 演进史。openspec `changes/archive/` 关注的是**变更追踪**（why + tasks + spec deltas），而这些文件是**完整 spec 草稿**（P0 sprint、T0 v1→v3），属于不同维度的历史。**实测 T0 三版（06-20/21/22）在 openspec 里无对应 change**，是 OpenSpec 立项前的产物，正好印证"docs/specs-history/ 承载 OpenSpec 接管前的完整 spec 演进"。 |
| [docs/designs/plans/](../docs/designs/plans/) + [docs/designs/specs/](../docs/designs/specs/) | **保留** | 是大块功能（Vue 交易系统、holdings 查询）的"设计 + 实施计划"对，跟 OpenSpec 里的"单个 change"颗粒度不同。OpenSpec change 解决小步快跑；这些是阶段性大型设计。 |
| [docs/msgpacket-python-api.md](../docs/msgpacket-python-api.md) | **保留** | 单一外部 API 参考。OpenSpec `rpc-protocol` capability 描述的是**契约面**（字段对齐、版本兼容），这文件是**底层 msgpacket 库的 Python API 速查**。 |

### 长期约定

- **新功能的真相源** → [openspec/specs/](../openspec/specs/)（改之前先看 [AGENTS.md](../openspec/AGENTS.md) 步骤 0）
- **新变更的工作流** → [openspec/changes/](../openspec/changes/) + `openspec-*` skill
- **历史 spec 演进、外部 API 速查、阶段性大型设计** → [docs/](../docs/)
- **不再有 PROJECT_ANALYSIS_REPORT.md / `initial-analysis.md` 这种"全景式"文档**——已多次被 override，污染知识库

## 影响的 capability

- `dev-process-control` — 目录约定本身就是开发流程的一部分

## 不做什么

- 不合并目录
- 不把 docs/specs-history 迁入 openspec/changes/archive（不同语义维度）
- 不动 msgpacket-python-api.md
- 不动 designs/（大块设计与单步 change 颗粒度不同）

## 验证

- `ls docs/` 应只剩 4 个入口：`archive/`（清空或删）、`designs/`、`msgpacket-python-api.md`、`specs-history/`
- `grep -r "docs/archive" openspec/ docs/` 应无引用
- [openspec/AGENTS.md](../openspec/AGENTS.md) 步骤 0 保持不变（不引用 docs/archive）
