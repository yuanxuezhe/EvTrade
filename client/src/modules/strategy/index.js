/**
 * strategy/index.js — strategy 业务模块 facade（task 11.1）
 *
 * 入口约定：
 *   视图层只从此处导入
 *     import { StrategyConfig, RegimeEditor, GridEditor,
 *              StrategyMonitor, FlagPicker } from '@/modules/strategy'
 *     import { useStrategy, useFlagDefinitions } from '@/modules/strategy'
 *
 * 禁止深层路径引入：
 *     import StrategyConfig from '@/modules/strategy/StrategyConfig.vue'  // ❌
 */
export { default as StrategyConfig } from './StrategyConfig.vue'
export { default as RegimeEditor } from './RegimeEditor.vue'
export { default as GridEditor } from './GridEditor.vue'
export { default as StrategyMonitor } from './StrategyMonitor.vue'
export { default as FlagPicker } from './FlagPicker.vue'

export { useStrategy, STATUS_LABEL, STATUS_TYPE, TYPE_LABEL, TYPE_TAG_TYPE } from './composables/useStrategy'
export { useFlagDefinitions } from './composables/useFlagDefinitions'