# risk-management — 风险档位与仓位管理

## Purpose

T0 交易需要对单股仓位、现金预留、配平系数等关键风险参数做统一管理。phase-2 把散落在 `T0Trade.vue` 内的 inline `RISK_CONFIGS` 常量抽到独立模块 `client/src/constants/riskProfile.js`，建立单一事实源，便于:

- 多个 view / composable 复用（未来扩 AlgoStrategy 等策略页时无需复制配置）
- 单元测试覆盖（4 档配置数值校验）
- 后端策略服务对齐（如需）

## Requirements

### REQ-RISK-001: 风险档位枚举（4 档）

系统提供 4 档风险配置，按风险递增排序：

| profile | label | maxSinglePosition | reserveCash | suggestedCoeff | tone |
|---|---|---|---|---|---|
| `conservative` | 🛡 保守 | 0.10 (10%) | 0.50 (50%) | 0.5 | success |
| `balanced` | ⚖ 平衡 | 0.25 (25%) | 0.30 (30%) | 1.0 | info |
| `aggressive` | 🔥 激进 | 0.50 (50%) | 0.10 (10%) | 1.5 | warning |
| `extreme` | 💥 极限 | 0.70 (70%) | 0.05 (5%) | 2.0 | danger |

**字段语义**:
- `maxSinglePosition` — 单股仓位占总资产上限（软警告阈值，超出则在 `riskWarnings` 提示）
- `reserveCash` — 必须预留的现金占总资产比例（影响 `maxBuyQty` 计算）
- `suggestedCoeff` — 一键配平默认系数（profitRate 在中性区间时使用）
- `label` — 展示用 emoji + 中文名
- `tone` — el-radio-button 配色提示（success/info/warning/danger）

**默认档**: `balanced`

### REQ-RISK-002: 模块导出契约

`client/src/constants/riskProfile.js` 必须导出:

```js
// 枚举（按风险递增）
export const RISK_PROFILES = ['conservative', 'balanced', 'aggressive', 'extreme']

// 默认档（store 初始值）
export const DEFAULT_RISK_PROFILE = 'balanced'

// 配置 dict（profile → config）
export const RISK_CONFIGS = { conservative: {...}, balanced: {...}, ... }

// 安全 getter（未知 profile 回退到默认档,避免 undefined 异常）
export function getRiskConfig(profile)

// el-radio-button 选项数组（按风险递增）
export const riskProfileOptions = [
  { value: 'conservative', label: '🛡 保守', tone: 'success' },
  ...
]
```

### REQ-RISK-003: T0Trade.vue 接入

`client/src/views/T0Trade.vue` 必须:

1. **从 constants 模块导入**:
   ```js
   import { RISK_CONFIGS, DEFAULT_RISK_PROFILE, getRiskConfig, riskProfileOptions } from '../constants/riskProfile'
   ```

2. **使用 getter 而非直接索引**:
   ```js
   const riskProfile = ref(DEFAULT_RISK_PROFILE)
   const riskConfig = computed(() => getRiskConfig(riskProfile.value))
   ```

3. **radio group 渲染 4 档**:
   ```html
   <el-radio-group v-model="riskProfile" size="large">
     <el-radio-button value="conservative">保守</el-radio-button>
     <el-radio-button value="balanced">平衡</el-radio-button>
     <el-radio-button value="aggressive">激进</el-radio-button>
     <el-radio-button value="extreme">极限</el-radio-button>
   </el-radio-group>
   ```

## Scenarios

### S-RISK-001: 切换到极限档位

Given 用户登录 T0Trade，默认 `balanced`
When 点击「💥 极限」radio button
Then `riskConfig.maxSinglePosition` = 0.70
And `riskConfig.reserveCash` = 0.05
And `maxSingleAmount` = totalAsset × 0.70
And `reserveAmount` = totalAsset × 0.05
And `maxBuyQty` 显著上升（受 70% 仓位上限放宽）
And 若当前仓位比 ≥10% 时，「⚠ 高风险」标签亮起

### S-RISK-002: 未知 profile 安全回退

Given localStorage 中存储了陈旧值 `"super-extreme"`（不在 4 档枚举中）
When `getRiskConfig("super-extreme")` 被调用
Then 返回 `RISK_CONFIGS["balanced"]` 而非 `undefined`
And 页面正常渲染，不报错

### S-RISK-003: 一键配平系数

Given `riskProfile = "conservative"`，profitRate 在中性区间 (-5% < pr < 10%)
When `suggestedCoeff` 计算
Then 返回 `RISK_CONFIGS.conservative.suggestedCoeff` = 0.5

Given `riskProfile = "extreme"`，profitRate 在中性区间
When `suggestedCoeff` 计算
Then 返回 `RISK_CONFIGS.extreme.suggestedCoeff` = 2.0

## File Layout

| 文件 | 职责 |
|---|---|
| `client/src/constants/riskProfile.js` | RISK_CONFIGS 单一事实源，4 档配置 + getter + options |
| `client/src/views/T0Trade.vue` | 导入并使用，不持有 inline 副本 |

## Known Issues

- 🟡 后端目前**未**校验下单时是否符合用户当前风险档位，纯前端软警告。后续可加风控中间件（POST /api/orders/place 时检查仓位）
- 🟡 风险档位**未**持久化（页面刷新回到 `balanced`）。后续可加 localStorage 同步或后端用户 profile 字段
