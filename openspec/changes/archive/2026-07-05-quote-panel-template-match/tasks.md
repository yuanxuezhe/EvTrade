# Tasks — quote-panel-template-match

按依赖顺序, 1 commit。

## 1. QuotePanel.vue 模板重排版 + 改 click-to-apply (commit: refactor(client))

- [x] 1.1 改 `client/src/components/QuotePanel.vue` 模板:
  - 删原 4 区结构 (标题 / hero / 6 格 grid / 3 列横排 orderbook)
  - 新 5 区结构按 `行情模板.png`:
    - **头部**: Symbol (▲/▼/▬) + 股票名 + 代码
    - **hero**: 大最新价 + 涨跌额 + 涨跌幅 (同 v15 配色)
    - **委比/委差 row**: 单 label + 委比% + 委差 *(r3 删除)*
    - **卖盘纵栈 5 行**: 卖5→卖1, 每行 `档位 / 价格 / 量`; hover 态 + tooltip "点击带入委托价", `@click="emitApply(...)"`
    - **中间最新价浮标**: 1 行粘接卖 1 价, 不可点击 *(r3 删除)*
    - **买盘纵栈 5 行**: 买1→买5, 同上 click-to-apply
    - **16 格 stats grid** (`grid-template-columns: 1fr 1fr`, `grid-template-rows: repeat(8, auto)`): label-left / value-right, 已计算字段填实, 未支持 (`现手 / 量比 / 市值 / 费率`) 显示 `—` + tooltip "待 broker 支持" *(r3 Row1 首格 `最新`→`昨收`)*
- [x] 1.2 改 `<script setup>`:
  - 加 computed: `avgPrice = amount/volume`, `amplitude = (high-low)/prevClose`, `limitUp/limitDown = prevClose * 1.10/0.90`, `committeeDiff = Σ bid - Σ ask`, `committeeRatio = committeeDiff / (Σ bid + Σ ask) * 100` *(r3 删除 committeeDiff/committeeRatio)*
  - 加 helper `formatNum` / `formatBigNum` / `signClass`
  - 改 `@dblclick` → `@click` (`:title` 改 `点击带入委托价`)
  - 保留现有 `tick` / `lastPrice` / `changePct` computeds
- [x] 1.3 改 `<style scoped>`:
  - 删 `.qp-grid / .qp-cell / .qp-orderbook` 6 格 + 3 列横排样式
  - 加 `.qp-stack / .qp-stack-ask / .qp-stack-bid` 卖/买纵栈
  - 加 `.qp-row / .qp-row:hover / .qp-row.is-disabled` 可点击行
  - 加 `.qp-stats-grid / .qp-stats-cell` 16 格 grid
  - 加 `.qp-hero.is-clickable / .qp-stats-cell.is-clickable` hover 态 *(r3)*
  - 保留 `.text-up / .text-down / .text-flat`
- [x] 1.4 验证:
  - `cd client && npm test -- --run` → 103 单测全过 (无 QuotePanel unit test)
  - `cd client && npx vite build` → 构建通过
  - grep 验证: `QuotePanel.vue` 不含 `@dblclick` / `.qp-grid` / `.qp-orderbook` / `.qp-committee` / `.qp-mid`; 含 `@click="emitApply"` / `.qp-stack` / `.qp-row` / `.qp-stats-grid` / `.qp-hero.is-clickable` / `.qp-stats-cell.is-clickable`
- [ ] 1.5 手动 UI smoke (dev 起后浏览器走一遍):
  - `/trade` 输入 `159992` 等 ETF 代码 → QuotePanel 头部渲染 `▲ 创新药ETF银华 159992`, **代码字体变大** (18px, 居右)
  - 大最新价 + 涨跌额 + 涨跌幅 在 hero 行显示 *(r3 hero 整行可点击带价)*
  - 卖盘 5 行紧贴 hero, 买盘 5 行紧贴卖盘 *(r3 移除中间最新价浮标)*
  - 5 档卖/买价量 缺档时显示 `—` 不塌陷
  - **所有"价格"cells 单击带价**: hero 大价 + 卖/买 5×2 价 + stats 7 格 (昨收/开盘/最高/最低/均价/涨停/跌停) — 共 18 个可点击 cell, hover 态有 bg + cursor + tooltip
  - 16 格 stats grid 全 16 格可见; `昨收` 已在 Row1 (替代 v14 的 `最新`, 因为 hero 已显); `均价 / 振幅 / 涨停 / 跌停` 字段已填实; `现手 / 量比 / 市值 / 费率` 显示 `—`
  - 视口 < 1100px 触发响应式 (`Trade.vue` 已 `/trade` 切单列, QuotePanel 跟随父级 flex 链, 无需新加响应式)

## 2. ~~委比/委差 row~~ — r3 移除 (覆盖原方案)

- [x] 2.1 移除 `<div class="qp-committee">` template 块 (含 `committeeDiff` / `committeeRatio` 两个 cell)
- [x] 2.2 移除 `.qp-committee` CSS 块
- [x] 2.3 移除 `<script setup>` 中 `committeeDiff` / `committeeRatio` / `committeeDiffText` / `committeeRatioText` 四个 computed 及 `sumAskVol` / `sumBidVol` helper (无引用, 避免死代码)

## 3. r3: hero / stats 价格格全部可点 + 昨收入 stats (commit: refactor(client) §r3)

- [x] 3.1 hero 整行加 `@click="emitApply(lastPrice)"` + `is-clickable` 条件类 + `title="点击带入委托价"`, CSS `.qp-hero { padding: 4px 8px; border-radius: 3px; transition: background .15s }` + `.qp-hero.is-clickable:hover { background: var(--bg-hover) }`
- [x] 3.2 stats grid Row1 首格 `最新` → `昨收` (`formatNum(prevClose)`), 加 `@click="emitApply(prevClose)"` + `is-clickable` + title
- [x] 3.3 stats grid 7 个价格格加可点击: 昨收 (3.2) + 开盘 + 最高 + 最低 + 均价 + 涨停 + 跌停, CSS `.qp-stats-cell.is-clickable { cursor: pointer; transition: background .15s }` + `:hover { background: var(--bg-hover) }`
- [x] 3.4 `.qp-code { font-size: 13px }` → `18px; font-weight: 600; letter-spacing: 0.5px` (证券代码字号变大)
- [x] 3.5 删除 `<div class="qp-mid">` 中间最新价浮标 (hero 已显示最新, 重复); 删 `.qp-mid` / `.qp-mid-label` / `.qp-mid-price` CSS
- [x] 3.6 验证 (回归): `cd client && npm test -- --run` → 103 全过; `cd client && npx vite build` → OK; `grep -c 'qp-committee\|qp-mid' client/src/components/QuotePanel.vue` → 0
