# M-008 快速做T — 设计修订 v3 (final)

**生效日期**: 2026-06-20
**关联**: docs/SPEC-t0-quick-redesign-v2.md (v2 主体仍有效, 本文件为 v3 增量)
**用户最终拍板**: B + A + A

---

## 0. 触发原因 (Why v3)

v2 commit `45b42b1` 后用户反馈:
> "我想 3 按钮坐在表格行里面 (买/卖/配平), 点对应行的按钮操作对应持仓.
>  点击行的时候, 右侧展开明细, 记录当前持仓的做T委托记录、收益之类的信息"

v2 把"操作"列做成 [详情] 单按钮 → 抽屉内才看到买卖. **违反用户"快速"诉求**:
- 抽屉要先开 → 找按钮 → 再点 → 至少 2-3 步
- v3: **行内 3 按钮直接下单** + **整行可点开明细** = 1 步下单 / 1 步看明细

---

## 1. v3 核心决策 (vs v2)

| 决策点 | v2 | v3 (用户拍板) |
|---|---|---|
| 操作列内容 | 1 个 [详情] 按钮 | **2 行: 上 3 按钮 (买/卖/配平) + 下 1 [明细] 按钮** |
| 整行点击 | 整行可点 → 抽屉 | **整行可点 → 抽屉** (保留) |
| 整行点 vs 按钮 | 都会触发 | **行内按钮 @click.stop 阻止冒泡** (点买不打开抽屉) |
| 抽屉作用 | 1 步: 找按钮下单 | **2 步: 看明细/历史/收益** (下单在行内完成) |
| 委托记录数据源 | 无 | **后端 t0_history API** (已有 endpoint) |
| "配平"语义 | 全仓净持仓清零 | **per 标的净持仓清零** (单只股票 T+0 锁仓) |

---

## 2. 操作列布局 (两行, 80-100px 宽)

```
┌─────────────────────┐
│  [⚡买] [⚠️卖] [⚖配] │  ← 第 1 行: 3 个实心按钮 (紧凑 32px 高)
│      [明细 →]       │  ← 第 2 行: 1 个 link 按钮 (详情入口)
└─────────────────────┘
```

**3 个按钮事件**:
| 按钮 | 触发 | 反馈 |
|---|---|---|
| ⚡买 | `onRowBuy(row)` | 弹 el-message-box 确认 → submitOrder (T0 买) → 提示"已委托" |
| ⚠卖 | `onRowSell(row)` | 同上 (T0 卖) |
| ⚖配 | `onRowBalance(row)` | 弹确认 "净持仓 100, 一键平仓?" → submitOrder (按差额) → 提示 |

**0 持仓限制** (用户拍板 A):
- ⚡买按钮 `:disabled="row.vol === 0"` (v3 严格)
- 0 持仓股票: 买按钮灰 + tooltip "0 持仓无法按比例买"
- 卖/配平按钮 0 持仓时: 0 股 = 无效, 提示后阻止

---

## 3. 整行点击 vs 按钮点击 (事件流)

```
@click.stop     ─┐
  [⚡买] ────────┤
  [⚠卖] ────────┼── 阻止冒泡 → 触发按钮事件 (下单)
  [⚖配] ────────┤
  [明细 →] ─────┘
               ↓  (无 stop)
  @row-click   ── → 触发 onRowOpenDrawer (打开抽屉)
```

`@row-click="onRowOpenDrawer"` (v2 已有, 保留)
+ 行内 3 按钮 `@click.stop="..."` (v3 新增, 阻止冒泡)
+ 整行 hover 高亮 (v2 已有 `ptRowClass`, 保留)

---

## 4. 抽屉内容 (搬自原 4 张卡 + t0_history API)

| 抽屉区块 | 数据源 | 字段 |
|---|---|---|
| 头部 | row | 代码/名称/现价/涨跌幅/操作时间 |
| 做T 委托记录 | `GET /api/orders/t0-history?code=xxx&date=...` | 时间/方向/价/量/状态/收益 |
| 累计收益 | `GET /api/orders/t0-aggregate?code=xxx&days=7/30/90` | 7/30/90 天累计已实现收益 |
| 敞口 | holdings store + 今日 t0 成交 | 当前持仓/今日买/今日卖/净持仓 |
| 配平建议 | computed | 按今日净额计算补仓量 |

**抽屉触发**: 点行/点 [明细] 按钮 → drawerVisible=true, 加载该 row.code 的 t0-history。

---

## 5. 改动文件 (v3)

| 文件 | 改动 |
|---|---|
| `client/src/views/T0Trade.vue` | 操作列 → 2 行 (3 按钮 + 1 详情); 整行点开抽屉; 3 按钮事件 |
| `client/src/views/T0Trade.vue` | 抽屉 el-drawer + 5 区块 (头部/历史/累计/敞口/配平) |
| `client/src/composables/useQuickT0.js` | 加 `onRowBalance(row)` 函数 (per 标的净持仓清零) |
| `client/src/composables/useQuickT0.test.js` | 加 onRowBalance 测试 |
| `docs/SPEC-t0-quick-redesign-v3.md` | 本文件 |

**不破坏**:
- v2 表格主结构 (代码/名称/持仓/现价/涨跌幅 列) ✅
- 顶置条 (commit 2) ✅
- 主表 max-height + sticky header (commit 3a) ✅
- useQuickT0.js 9 纯函数 (commit 1) ✅

---

## 6. 测试计划 (v3)

| # | 用例 | 通过条件 |
|---|---|---|
| T1 | 0 持仓 → 买按钮 disabled | el-button[disabled] |
| T2 | 0 持仓 → 卖按钮 click → 弹 "0 股 无效" | el-message-box |
| T3 | 整行 click → drawerVisible=true | drawer open |
| T4 | 行内 [买] click → 不打开抽屉 | drawerVisible=false, 提交订单 |
| T5 | onRowBalance(净持仓 100) → 下单 -100 (卖 100) | order.volume === 100 |
| T6 | t0_history 返回 0 记录 → 抽屉显示 "暂无委托" | empty state |
| T7 | 抽屉加载时 t0_history API 失败 → 显示错误重试按钮 | error UI |

---

## 7. DoD (Definition of Done)

- [ ] 操作列两行: 3 按钮 (买/卖/配平) + 1 [明细] 按钮
- [ ] 0 持仓 → 买按钮 disabled
- [ ] 整行 click → 打开抽屉 (后台加载 t0_history)
- [ ] 行内按钮 click → 阻止冒泡 (不开抽屉, 直接下单)
- [ ] 抽屉: 头部 + 委托记录表 + 累计收益 + 敞口 + 配平
- [ ] 配平按钮: 计算净持仓差额, 下反向单
- [ ] vitest: 0 持仓 + 阻止冒泡 + onRowBalance 净持仓清零 共 3+ 用例
- [ ] 截图回归: 行内 3 按钮 + 1 详情 + 抽屉打开后 5 区块完整
