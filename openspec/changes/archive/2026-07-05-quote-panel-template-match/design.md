## Context

`client/src/components/QuotePanel.vue` 当前实现 (`openspec/specs/frontend/spec.md` REQ-FE Trade.vue 路由表层引用) 渲染 4 个区:
1. 标题 (DataLine icon + "行情面板" + 股票代码 + "更新 Ns 前")
2. hero (大最新价 + 涨跌/涨跌幅 + 涨红跌绿配色)
3. 6 格 grid (今开/最高/最低/昨收/成交量/成交额, 双击带价)
4. 3 列横排 orderbook (卖 5..1 / 中间最新价 / 买 1..5, 双击带价)

参考图 `行情模板.png` 是 trader 习惯的 broker 终端风格:
- 标题头: 涨状态符 ("R" 表示 up) + 股票名 + 代码 → 大最新价 + 涨跌幅
- 卖盘纵栈 5 行 (档位 ↑ 价格 ↓ 量) — 卖 5 (顶) → 卖 1 (底)
- 买盘纵栈 5 行 — 买 1 (顶) → 买 5 (底)
- 16 格 2 列 stats (label-left / value-right): 昨收/开盘, 涨跌/最高, 涨幅/最低, 振幅/均价, 现手/金额, 总手/量比, 涨停/跌停, 市值/费率

**r3 修订**: 移除委比/委差 row + 中间最新价浮标; 证券代码字号 13→18px; stats Row1 首格由 `最新` 改为 `昨收` (hero 已显最新); hero + 7 个 stats 价格格全部可点击带价 (除 hero 共 18 个 price cell: hero 1 + 卖 5 + 买 5 + stats 7)。

`client/src/stores/quote.js` 提供 30 字段 (现价/开/高/低/昨收/量/额 + 卖/买各 5 价 5 量)。**缺**: 均价/振幅/涨停/跌停/现手/量比/市值/费率 (r3 委比/委差移除, 不再依赖)。

`Trade.vue` 已监听 QuotePanel emit 的 `apply-price` 事件 (调 `orderStore.setPrice`), 不动。

## Goals / Non-Goals

**Goals**:
- 视觉匹配 `行情模板.png` (标题 hero + 卖盘纵栈 + 买盘纵栈 + 16 格 stats)
- 单击 (click) 价格带入 OrderForm 委托价 (替代当前双击) — **所有价格格可点** (r3: hero + stats 价格格一并纳入)
- 客户端能计算的字段 (均价/振幅/涨停/跌停) 全部填实; 不能计算的 (现手/量比/市值/费率) 显示 "—"
- 不改 ws push / quote.js 数据契约
- emit `apply-price` 签名不变

**Non-Goals**:
- 不新加 broker 后端字段 (现手/量比/市值/费率暂不接)
- 不做"涨跌/振幅/量比"这些能计算的图表可视化 (只是文字数字)
- 不改 Trade.vue 外层布局
- 不做响应式 (mobile 行为另开 change)
- 不提供"复制价格"等次要操作 (本次只点→带价)
- **r3 排除**: 不再渲染委比/委差 (trader 反馈: 后端不支持口径, 视觉冗余)

## Decisions

| ID | 决策 | 理由 | 替代 |
|---|---|---|---|
| D1 | 卖/买盘布局: 卖盘 5 行纵栈 (5→1), 买盘 5 行纵栈 (1→5), **无中间浮标** (r3) | r3 移除 qp-mid 后视觉更紧凑, 视线直"卖压→买力"; hero 已显示最新价无需重复 | 保留中间最新价浮标 → 与 hero 重复, 占位 |
| D2 | ~~委比/委差~~ (r3 移除) | trader 反馈: 后端 5 档口径与全档口径有差异, 视觉冗余 | 留 5 档口径 → 易误导 |
| D3 | 涨跌停 = `prevClose * 1.10` / `prevClose * 0.90` | A 股主板 10% 通用规则; 创业板/科创板 20% / ST 5% 需另按 `stock_code` 前缀判断 — **本次简化为主板 10%, 留 TODO 注释**, 后续若 trader 误判再细化 | 查证股票板块前缀加规则 → 增加复杂度, 数据未在 push 内 |
| D4 | 均价/振幅: client-side 算 (`amount/volume` / `(high-low)/prevClose`) | 仅展示用, 前端 1 行算得 | 后端加 → 跨团队改动, 不在本次 scope |
| D5 | 3 个 client-side 衍生 (均价/振幅/涨/跌停); 4 字段不可计算 (现手/量比/市值/费率) 显示 "—" + tooltip 提示"待后端支持" | 立刻能做的全做, 不能做的明确告知 trader | 等 broker 字段再做 → 拖累进度 |
| D6 | 单击 `@click="emitApply(price)"` 替代 `@dblclick`; **覆盖 18 个 price cell** (r3: hero 1 + 卖 5 + 买 5 + stats 7) | trader 反馈: 所有"价格"cells 都应可点, 不限于 5 档盘口 | 仅 5 档可点 → 与"所有价格都能带"语义不符 |
| D7 | 卖盘背景色: `var(--ask-tint-bg)` 浅红; 买盘: `var(--bid-tint-bg)` 浅绿/青; 价格统一 `--color-up`(红) `text-flat`(黑) `text-down`(绿) | 与 broker 终端风格一致, 模板色系可对应 | 完全中性背景 → 视觉梯度无差异 |
| D8 | 16 格 stats 不分高亮颜色, 全部用 `--text-primary`; 正负值 (涨跌/涨幅) 用色 helper `<span :class="signClass(value)">` | trader 扫一眼数字即可; 不滥用色彩导致视觉噪声 | 每格颜色按语义 → 杂乱 |
| D9 | 数值精度: 价格字段 `String(num)` 保留原始精度 (与现有 QuotePanel 一致); 涨跌金额 `±X.XX` 2 位; 涨跌幅 `±X.XX%` 2 位; 振幅 `X.XX%` 2 位; 均价/涨跌幅与价格一致 | 与现有 `formatNum` / `formatBigNum` 保持一致 | 统一 4 位 / 2 位 → 丢失精度 |
| D10 | 持仓点击 hover 态: `cursor: pointer` + `.qp-row:hover { background: var(--bg-hover) }` + `title="点击带入委托价"` tooltip; **r3 扩展**: `.qp-hero.is-clickable:hover` + `.qp-stats-cell.is-clickable:hover` 同样态 | 明确告诉 trader 此 cell 可点击, 跨区域统一视觉反馈 | 无 hover hint → trader 不知道能点 |
| D11 (r3) | stats Row1 首格 `最新` → `昨收`; 证券代码 `.qp-code` 字号 13px → 18px + `font-weight: 600` + `letter-spacing: 0.5px` | trader 反馈: 头部代码字小不易扫读; "最新"已在 hero, 重复 | 保留 13px → 阅读疲劳; 保留"最新" → 视觉冗余 |

## Risks / Trade-offs

- [Limit up/down 规则过度简化] D3 简化为 10%, 创业板/科创板/ST 用户看到涨停价会错
  - 缓解: 加 `TODO(comment)` 标注"如需区分板块, 按 stockCode 前缀 (300/688) 或 broker 标签细化"; 当前市场主板占绝大多数, 影响有限
- [现手/量比/市值/费率 "—" 视觉留白] 4 个未支持的字段长期显示 "—", trader 误以为行情没数据
  - 缓解: tooltip `title="待 broker 推送支持"` 说明; 后续跟 broker 联调再补
- [r3 stats 价格格全部可点 → 18 个 emit 点] 若 trader 误点 `涨停/跌停` 等"非当前价"价格, 可能下一笔非市价单
  - 缓解: title 提示 "点击带入委托价"; OrderForm 限价字段已 `el-input-number` 数字, trader 仍能在提交前调整; 委托价类型默认 `限价`, 不冲突
- [el-table 不引入] 不切 `<el-table>` 仍用 div grid, 跟现有风格一致; trader 主要看数字, 不需要表格交互
  - 缓解: 维持现状
- [show "—" 与 ws 数据滞后] ws 推送可能暂缺某字段, 渲染层 try/parse 失败时也 "—"; 与"待 broker 支持"同视觉, 需点 hover 看 tooltip
  - 缓解: tooltip 区分 (TBD)

## Migration Plan

1. 单 commit: `refactor(client): QuotePanel 改 layout + click-to-apply + 衍生指标` (含 r3 修订)
2. 无 DB / API / 数据契约变更, 无需 migration 脚本
3. 回滚: 单 git revert 即可

## Open Questions

- 创业板/科创板涨停比例 20% 是否要做 (本次不做; trader 反馈再开 change)
- 4 个 "—" 字段是否要后端补 broker 字段 (后续与 broker 团队联调)
- ~~委比/委差 5 档口径~~ (r3 关闭, 字段不渲染)

## Refs

- 模板: `D:\workspace\EvTrade\行情模板.png`
- 当前: `client/src/components/QuotePanel.vue` (r3 ≈ 300 行)
- 数据源: `client/src/stores/quote.js` (30 字段)
- 调用点: `client/src/views/Trade.vue` (已监听 `@apply-price="onApplyPrice"`)
