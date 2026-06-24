# Risk-Management 能力 spec（新建）

## Purpose

T+0 交易风险档位配置 — 4 档（保守/平衡/激进/极限）枚举、模块契约、T0Trade 集成。

## Requirements

### REQ-RISK-001: 4 档风险档位

| 档位 | maxSinglePosition | reserveCash | suggestedCoeff | label | tone |
|---|---|---|---|---|---|
| conservative | 0.30 | 0.30 | 0.6 | 🛡 保守 | success |
| balanced | 0.50 | 0.20 | 1.0 | ⚖ 平衡 | primary |
| aggressive | 0.60 | 0.10 | 1.5 | ⚡ 激进 | warning |
| extreme | 0.70 | 0.05 | 2.0 | 💥 极限 | danger |

### REQ-RISK-002: 模块导出契约

- **位置**：`client/src/constants/riskProfile.js`
- **导出**：
  - `RISK_PROFILES = ['conservative', 'balanced', 'aggressive', 'extreme']`
  - `DEFAULT_RISK_PROFILE = 'balanced'`
  - `RISK_CONFIGS = { conservative: {...}, balanced: {...}, aggressive: {...}, extreme: {...} }`
  - `getRiskConfig(profile)` — 安全 getter（未知档位降级为 balanced）
  - `riskProfileOptions` — 选项数组（供 el-radio-group 使用）

### REQ-RISK-003: T0Trade 集成

- T0Trade.vue 风险档位 radio: 4 档（含 extreme）
- 切换档位 → `RISK_CONFIGS[profile]` 立即生效
- `maxSinglePosition` → 单一持仓上限（用于 T0 配平计算）
- `reserveCash` → 保留现金比例
- `suggestedCoeff` → 余额系数默认值（用户可改）

详见 `risk-management/spec.md` REQ-RISK-001..003 完整定义
