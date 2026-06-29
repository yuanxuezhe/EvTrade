# Spec Delta: dev-process-control

## MODIFIED Requirements

### Requirement: 文档目录双体系约定

> **新增** requirement。明确 [docs/](../../../docs/) 与 [openspec/](../../../openspec/) 是两套独立体系，**禁止合并**，并规定各自承载的文档类型。

The system SHALL maintain two non-overlapping documentation roots:

1. **[openspec/](../../../openspec/)** — 动态工作流：当前 spec 真相源（`specs/<cap>/spec.md`）、变更追踪（`changes/<name>/` + 配套 skill `openspec-*`）、AI 协作约定（`AGENTS.md`）、工具配置（`.openspec.yaml`、`config.yaml`）。
2. **[docs/](../../../docs/)** — 静态沉淀：被覆盖前的 spec 演进史（`specs-history/`）、阶段性大型设计与配套实施计划（`designs/`）、单一外部 API 速查（顶层 `*.md`）。

#### Scenario: 新增 spec 的正确位置

- **WHEN** 描述一个**当前实现的**能力（"系统 SHALL ..."）
- **THEN** 该 spec 写入 [openspec/specs/<cap>/spec.md](../../../openspec/specs/)；如果该能力由一个 OpenSpec change 引入，对应 change 归档时通过 `opsx:archive` 同步 delta 到该文件

#### Scenario: 历史 spec 草稿的正确位置

- **WHEN** 沉淀一份"被后续 spec 覆盖前的演进版本"（如 v1→v2→v3 的中间稿）
- **THEN** 写入 [docs/specs-history/](../../../docs/specs-history/)，文件名带版本后缀（如 `2026-06-22-t0-quick-redesign-v3.md`）；**不写入** [openspec/changes/archive/](../../../openspec/changes/archive/)——后者追踪"变更元数据"（proposal + tasks + spec deltas），前者承载"完整 spec 草稿"

#### Scenario: 阶段性大型设计的正确位置

- **WHEN** 沉淀一个跨多个 capability 的大型设计 + 实施计划（如 Vue 交易系统从 0 到 1）
- **THEN** 设计 + 计划对写入 [docs/designs/specs/](../../../docs/designs/specs/) 与 [docs/designs/plans/](../../../docs/designs/plans/)；**不拆为单个 OpenSpec change**——OpenSpec change 服务小步快跑，这种文件颗粒度不同

#### Scenario: 禁止的操作

- **WHEN** 用户/AI 提议"把 [docs/](../../../docs/) 合进 [openspec/](../../../openspec/)"或反之
- **THEN** 拒绝合并；如确有重叠，按本 requirement 的语义边界决定保留/删除哪一份
