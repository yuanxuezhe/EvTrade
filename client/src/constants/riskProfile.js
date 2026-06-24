/**
 * 风险档位配置 (T0 仓位管理)
 *
 * 4 档由保守到激进:
 *   conservative - 保守: 单股 ≤10%, 留 50% 现金, 系数 0.5x
 *   balanced     - 平衡: 单股 ≤25%, 留 30% 现金, 系数 1.0x  (默认)
 *   aggressive   - 激进: 单股 ≤50%, 留 10% 现金, 系数 1.5x
 *   extreme      - 极限: 单股 ≤70%, 留  5% 现金, 系数 2.0x  ⚠ 高风险
 *
 * 字段语义:
 *   maxSinglePosition  - 单股仓位占总资产上限 (软警告阈值)
 *   reserveCash        - 必须预留的现金占总资产比例
 *   suggestedCoeff     - 一键配平默认系数
 *   label              - 展示用 emoji + 中文名
 *   tone               - el-radio-button 配色提示 ('success' | 'info' | 'warning' | 'danger')
 */
export const RISK_PROFILES = ['conservative', 'balanced', 'aggressive', 'extreme']

export const DEFAULT_RISK_PROFILE = 'balanced'

export const RISK_CONFIGS = {
  conservative: {
    maxSinglePosition: 0.10,
    reserveCash: 0.50,
    suggestedCoeff: 0.5,
    label: '🛡 保守',
    tone: 'success',
  },
  balanced: {
    maxSinglePosition: 0.25,
    reserveCash: 0.30,
    suggestedCoeff: 1.0,
    label: '⚖ 平衡',
    tone: 'info',
  },
  aggressive: {
    maxSinglePosition: 0.50,
    reserveCash: 0.10,
    suggestedCoeff: 1.5,
    label: '🔥 激进',
    tone: 'warning',
  },
  extreme: {
    maxSinglePosition: 0.70,
    reserveCash: 0.05,
    suggestedCoeff: 2.0,
    label: '💥 极限',
    tone: 'danger',
  },
}

/**
 * 按 profile 取配置, 未知 profile 退回默认档
 */
export function getRiskConfig(profile) {
  return RISK_CONFIGS[profile] || RISK_CONFIGS[DEFAULT_RISK_PROFILE]
}

/**
 * el-radio-button 选项 (按风险递增排序)
 */
export const riskProfileOptions = RISK_PROFILES.map(p => ({
  value: p,
  label: RISK_CONFIGS[p].label,
  tone: RISK_CONFIGS[p].tone,
}))
