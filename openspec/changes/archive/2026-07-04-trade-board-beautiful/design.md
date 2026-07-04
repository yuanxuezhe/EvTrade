## Context

`client/src/components/OrderForm.vue` 在 `client/src/views/Trade.vue` 左列 (`.trade-form-col`) 内渲染。
当前模板用 `<div class="price-row">` grid `auto 1fr` 把 `价格类型` 与 `委托价格` 横向并排; `.price-type-col { min-width: 180px }` 给 segmented 留硬下限宽度; `.price-col` 占剩余 1fr。

`价格类型` 用 `el-segmented` 渲染 4 段 (`限价 / 最新价 / 挂单价 / 市价`)。在左列窄宽 + `.price-row` 把 segmented 限制在 `auto (min 180px)` 宽度下, segmented 实际可用宽度 < 180px 时, 4 个 label 文字被压缩 / 截断 / 报空白。`委托数量` 由于本来就独立 `<el-form-item>` 占满整行, 不受影响。

用户决策 (1 项):
- 3 个字段独立成行: `价格类型` / `委托价格` / `委托数量` 各自占满 `<el-form>` 100% 宽度

## Goals / Non-Goals

**Goals**:
- `价格类型` segmented 在左列窄宽度下 4 个 label 全部完整可见
- 3 个字段每段占满表单 full row, 与 `<el-form label-position="top">` 配合保持垂直节奏
- layout-only 改动, script / data 契约 / 行为全部保持不变

**Non-Goals**:
- 不改 `el-segmented` 选项数据 (`priceTypeOptions`), 不加隐藏选项
- 不改 `.volume-quick` 数量快捷按钮位置 (它仍在 `委托数量` 段内)
- 不改 `Trade.vue` 外层布局 (`.trade-form-col` flex 链仍是 v13 默认)
- 不做响应式 (mobile/折叠屏另开 change)
- 不动颜色 / 字体 / 主题变量

## Decisions

| ID | 决策 | 理由 | 替代方案考虑 |
|---|---|---|---|
| D1 | `价格类型` 段去掉 `.price-type-col { min-width: 180px }` | 整行宽下不再需要硬下限, segmented 自然撑到表单宽 | 保留 min-width → 验证未果, segmented 仍在窄列边缘挤压 |
| D2 | `委托价格` 段升级为独立 `<el-form-item>` (与 `委托数量` 对称) | 用户明确要求"和委托数量一样单独一行" | 双行字段组合 + responsive → 过度设计, 用户没要 |
| D3 | 删 `.price-row` grid 容器 | grid 不再需要; 也删 `.price-col` (未引用) | 保留 grid + `grid-template-columns: 1fr` (单列) → 等价但冗余 |
| D4 | 字段顺序保持 `股票代码 → 价格类型 → 委托价格 → 委托数量` | 用户指定"价格类型下面, 委托数量上面" | 倒序或重排 → 不符合用户意图 |
| D5 (r2) | 价格类型从 `<el-segmented block size="small">` 改为 `<el-radio-group>` + `<el-radio border>` + CSS Grid 2×2 布局 | 探索后收口选 C: 2×2 grid 充分利用 `.trade-form-col` 480px 全宽, 每格独占 ≈ 220px, 4 个 label (`限价` / `最新价` / `市价` / 未来更长 label) 完整可见; 同时换 `el-radio-group` 切换整组交互 (无 segmented 滑动 indicator), 更符合 radio 语义 (互斥选择非"滑动高亮") | A: min-width CSS 改动小但未根除 segmented label ellipsis 风险 (后续长 label 仍挤压); B: el-radio-button 仍是横向 1 行, 4 段在窄列仍有挤压; D: 2x2 grid 用 `el-radio` 视觉更"现代", 符合用户给的 ASCII mockup  |

## Risks / Trade-offs

- [垂直高度膨胀] 3 段占满全宽, 总高度可能比之前 `auto 1fr` 多 30~50px → 影响 `.trade-form-col` flex 链均分左列高度
  - 缓解: `.trade-form-col > * { flex: 1 1 0; min-height: 0; overflow: hidden }` (frontend 已规定) 已允许 overflow; OrderForm 自带 `overflow: hidden` (`order-form-wrap`), 段多不会顶破列容器
- [el-radio 2x2 grid 视觉一致性] `<el-radio border>` 在 Element Plus theme 下视觉是"带边框的 radio button", 与原 `<el-segmented>` (实心填充 indicator) 视觉风格不同; 用户已确认接受此风格
  - 缓解: 已在 design D5 (r2) 中确认; 若后续反馈不喜欢, 可切回 A (保留 segmented + min-width) 或 B (el-radio-button 1 行)
- [交互习惯变动] segmented → radio 改变交互习惯 (segmented 是"水平滑动高亮", radio 是"互斥 radio 圆点"); trader 下单节奏可能受影响
  - 缓解: 1 次 click 切换选中状态, 语义等价; 切换速度不慢于 segmented

## Migration Plan

1. 单 commit: `refactor(client): OrderForm 价格类型/委托价格/委托数量 拆 3 行独立`
2. 无 DB / API / 数据流变更, 无需 migration 脚本
3. 回滚: 单 git revert 即可

## Open Questions

(无 — 用户输入已收敛)
