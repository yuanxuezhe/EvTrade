<!--
  PriceTypeInput.vue — 委托价格 + 价格类型 组合组件 (v33.1, 改造为 StockCodePicker 风格)

  沿用 v28 StockCodePicker (.scp- 前缀) 视觉骨架 (实测贴一起, baseline 对齐), 改前缀 pti-:
  - 左 50% el-input (类型 number, 无 controls): 输入价格 (FIX_PRICE 启用; 市价/最新价 只读)
  - 右 50% el-select: 价格类型 (限价/最新价/市价)
  - 默认 PriceType.FIX_PRICE (11 = 限价)

  用户反馈 v33 上线后样式丑 ("委托价格组件很丑"), 原因:
    - 用了 el-input-number 自带 +/- controls → "上下箭头" 与 StockCodePicker 风格不一致
    - 高度 / line-height / border-radius 与左侧 StockCodePicker 不一致
  修复 (v33.1):
    - 左改用 el-input + type=number + 自定义精度 (无 controls)
    - 全部 CSS 完全镜像 v28 .scp- 骨架 (baseline 对齐, 1px 衔接, box-shadow 同色)

  Props:
    - price      (Number|String) : v-model:price
    - priceType  (Number)        : v-model:priceType, 默认 PriceType.FIX_PRICE (11)
    - disabled   (Boolean)       : 是否禁用整个组件
    - placeholder(String)        : 左 input 占位符
    - size       (String)        : 'default' (默认) | 'small' | 'large'
    - width      (String|Number) : 整体宽度, 默认 '100%'
    - inputRatio (Number)        : 左(input) 权重, 默认 1 (50%)
    - nameRatio  (Number)        : 右(select) 权重, 默认 1 (50%)

  Emits:
    - update:price      (Number|String)
    - update:priceType  (Number)
-->
<template>
  <div class="pti-wrapper" :class="`is-${size}`" :style="wrapperStyle">
    <!-- 左: 价格 input (无 controls, 单 input) -->
    <div class="pti-price-input" :style="priceInputStyle">
      <el-input
        v-model="localPrice"
        type="number"
        :placeholder="placeholder || defaultPlaceholder"
        :disabled="disabled || isNonFixedPrice"
        :size="size"
        class="pti-el-input"
        @input="onPriceInput"
        @blur="onPriceBlur"
      />
    </div>
    <!-- 右: 价格类型 select -->
    <div class="pti-select-box" :style="selectBoxStyle">
      <el-select
        v-model="localPriceType"
        :disabled="disabled"
        :size="size"
        :placeholder="placeholder || defaultPlaceholder"
        class="pti-el-select"
      >
        <el-option
          v-for="opt in priceTypeOptions"
          :key="opt.value"
          :label="opt.label"
          :value="opt.value"
        />
      </el-select>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { PriceType, priceTypeOptions } from '../constants/priceType.js'
import { useStocksStore } from '../stores/stocks'

const props = defineProps({
  price: { type: [Number, String], default: null },
  priceType: { type: Number, default: PriceType.FIX_PRICE },
  disabled: { type: Boolean, default: false },
  placeholder: { type: String, default: '' },
  size: { type: String, default: 'default' },
  width: { type: [String, Number], default: '100%' },
  inputRatio: { type: Number, default: 1 },
  nameRatio: { type: Number, default: 1 },
  // v82: 证券代码 — 用于按 scale 四舍五入价格
  stockCode: { type: String, default: '' },
})

const stocksStore = useStocksStore()
// 按 scale round 价格 (el-input type=number 没有 :precision 属性, 用 onPriceInput 主动 round)
const priceScale = computed(() => stocksStore.stockScale(props.stockCode))

const emit = defineEmits(['update:price', 'update:priceType'])

// v-model:price
const localPrice = computed({
  get: () => props.price,
  set: (v) => emit('update:price', v),
})

// v-model:priceType
const localPriceType = computed({
  get: () => props.priceType,
  set: (v) => emit('update:priceType', v),
})

// FIX_PRICE 启用 input; 其他 (LATEST_PRICE / MARKET_PEER) → input 只读 (行情价自动)
const isNonFixedPrice = computed(() => props.priceType !== PriceType.FIX_PRICE)

// placeholder 自动切换
const defaultPlaceholder = computed(() =>
  props.priceType === PriceType.FIX_PRICE ? '输入价格' : '行情价(自动)'
)

// 宽度/占比计算 — 完全复用 scp 模式 (v28-2)
const wrapperStyle = computed(() => {
  const w = typeof props.width === 'number' ? `${props.width}px` : props.width
  return { width: w }
})

const inputBasisPercent = computed(() => {
  const total = Math.max(0.0001, props.inputRatio + props.nameRatio)
  return (props.inputRatio / total) * 100
})

const priceInputStyle = computed(() => ({
  flex: `0 0 ${inputBasisPercent.value}%`,
  width: `${inputBasisPercent.value}%`,
  minWidth: 0,
}))

const selectBoxStyle = computed(() => ({
  flex: `0 0 calc(${100 - inputBasisPercent.value}% + 1px)`, // v28-8: 多吃 1px 抵消左 wrapper inset shadow
  width: `calc(${100 - inputBasisPercent.value}% + 1px)`,
  minWidth: 0,
}))

// el-input type=number 输入处理
//
// v107.2 (2026-08-17): 统一价格输入 UX 契约
//   1. input 时: 按 stockScale 截断小数位 (超位即切尾, 输不进去)
//   2. input 时: 不补 0 / 不 toFixed (避免光标跳转)
//   3. blur 时:  按 stockScale toFixed 补 0 留盘 (与 formatPrice 显示口径一致)
//   与 v82 el-input-number + :precision 组件语义一致, 适用于 type="number" 这种无内置 precision 的场景.
//
// 历史踩坑:
//   v106: emit "1.00" 字符串 → el-input v-model 转 Number 后变 1 → 输入流被锁死, "输 1.2 变 1.002"
//   v107: emit 原 Number → emit 0.7 → el-input 强写 "0.7" → 中间态 "0.70" 被吞, "0 打不出来"
//   v107.1: emit 原字符串 → 解除光标锁定, 但出现 "0.7018" 不规范值也会保留
//   v107.2 (当前): emit 原字符串 + 按 scale 截断小数 → 输 "0.70" 截到 3 位仍是 "0.70" (合法),
//     输 "0.7018" → 截到 "0.701" (超 3 位即切), 输 "0.7" 原样保留, blur 时再补 0.
//
// scale 来源: stocksStore.stockScale(props.stockCode)
//   股票 (000001.SZ): scale=2
//   ETF (513050.SH): scale=3
//   cache miss → 兜底 2
function onPriceInput(v) {
  // el-input type=number 在中间态 (".", "0.", "") 时 v 可能是 "" / "." / "0." — 都原样 emit
  if (v === '' || v === null || v === undefined) {
    emit('update:price', v)
    return
  }
  // 仅处理 string (element-plus v-model 走 input 事件传 string); 兜底也接受 number
  const s = String(v)
  // 按 scale 截断小数位 (Math.trunc 不四舍五入) — 超过 scale 的位直接截掉, 用户输不进去
  //   scale=3, 输 "0.70"  → s="0.70"  → 截断后 "0.70"  → emit "0.70"
  //   scale=3, 输 "0.701" → s="0.701" → 截断后 "0.701" → emit "0.701"
  //   scale=3, 输 "0.7018" → s="0.7018" → 截断后 "0.701" → emit "0.701" (第 4 位被切)
  //   scale=3, 输 "0.7"   → s="0.7"   → 截断后 "0.7"   → emit "0.7" (不足 3 位不补, blur 时补)
  //   scale=3, 输 "0."    → s="0."    → 截断后 "0."    → emit "0." (中间态不动)
  const p = priceScale.value
  const dotIdx = s.indexOf('.')
  if (dotIdx >= 0 && p >= 0) {
    const intPart = s.slice(0, dotIdx)
    const fracPart = s.slice(dotIdx + 1)
    if (fracPart.length > p) {
      const truncated = intPart + '.' + fracPart.slice(0, p)
      emit('update:price', truncated)
      return
    }
  }
  // 不超位 / 无小数点 / 非数字 — 原样 emit, 不补 0 不 toFixed
  emit('update:price', s)
}

// v107.2: 失焦统一按 scale 落盘 + 非数字清空
//   输入过程中已 emit 原字符串 + 超位截断, 不再干预; 失焦时一次性按 scale toFixed 补 0 留盘
//   例: scale=3, "0.7"  → 0.700 (toFixed 补 0); "0.70" → 0.700; "0.701" → 0.701
function onPriceBlur() {
  const v = localPrice.value
  if (v === '' || v === null || v === undefined) return
  const n = Number(v)
  if (!Number.isFinite(n)) {
    emit('update:price', '')
    return
  }
  const p = priceScale.value
  // toFixed 补 0 (按 scale 精度补 0, 与显示 formatPrice 一致)
  const fixed = n.toFixed(p)
  if (String(n) !== fixed && String(v) !== fixed) {
    emit('update:price', fixed)
  }
}
</script>

<style scoped>
/* === v33.1: 完全镜像 v28 StockCodePicker 视觉骨架 ===
   - 两段贴一起, 1px 衔接, 同色 box-shadow
   - 整体高度 33px, line-height 30px
   - 字号 13px (与 scp tag-text 字号一致)
   - border-radius: 左 input 右侧 0 / 右 select 左侧 0
*/

.pti-wrapper {
    display: flex;
    gap: 0;
    align-items: stretch;
    width: 100%;
    box-sizing: border-box;
}

.pti-price-input {
    min-width: 0;
    box-sizing: border-box;
    display: flex;
}

/* el-input 撑满 wrapper */
.pti-el-input {
    width: 100%;
}

/* v28-19/20: 强制 .el-input 从 inline-flex 改 flex, 消除 baseline 偏移 1.30px
   仅 default size — small 下 inline-flex 即可, 不需要这个 hack (el-input 自身会管) */
.pti-wrapper:not(.is-small) .pti-el-input :deep(.el-input) {
    display: flex !important;
    vertical-align: top !important;
}

/* 左 input: 清右半圆角 (右 select 接管)
   small 用 Element Plus 的 --el-border-radius-small (4px), default 用 8px — 圆角跟 size 联动 */
.pti-el-input :deep(.el-input),
.pti-el-input :deep(.el-input__wrapper),
.pti-el-input :deep(.el-input__inner) {
    border-top-right-radius: 0 !important;
    border-bottom-right-radius: 0 !important;
}
.pti-wrapper.is-small .pti-el-input :deep(.el-input),
.pti-wrapper.is-small .pti-el-input :deep(.el-input__wrapper),
.pti-wrapper.is-small .pti-el-input :deep(.el-input__inner) {
    border-top-left-radius: var(--el-border-radius-small, 4px) !important;
    border-bottom-left-radius: var(--el-border-radius-small, 4px) !important;
}

/* 默认 / hover / focus box-shadow 都吃 inset 1px, 与右侧 select 衔接处一致色 */
.pti-wrapper:not(.is-small) .pti-el-input :deep(.el-input__wrapper),
.pti-wrapper:not(.is-small) .pti-el-input :deep(.el-input__wrapper.is-focus),
.pti-wrapper:not(.is-small) .pti-el-input :deep(.el-input__wrapper:hover),
.pti-wrapper:not(.is-small) .pti-el-input :deep(.el-input__wrapper:focus-within) {
    box-shadow: 0 0 0 1px rgb(232, 237, 245) inset !important;
    border-top-right-radius: 0 !important;
    border-bottom-right-radius: 0 !important;
}

/* hover: 浅 primary 边框 */
.pti-wrapper:not(.is-small) .pti-el-input :deep(.el-input__wrapper:hover) {
    box-shadow: 0 0 0 1px var(--el-color-primary-light-5, #c0d4f7) inset !important;
}

/* focus: primary 边框 */
.pti-wrapper:not(.is-small) .pti-el-input :deep(.el-input__wrapper:focus-within),
.pti-wrapper:not(.is-small) .pti-el-input :deep(.el-input__wrapper.is-focus) {
    box-shadow: 0 0 0 1px var(--el-color-primary, #409eff) inset !important;
}

/* v33.1: 隐藏浏览器原生 number input 的上下箭头 spinners (Chrome/Safari/Firefox/Edge) */
.pti-el-input :deep(.el-input__inner) {
    appearance: textfield !important; /* Firefox */
}
.pti-el-input :deep(.el-input__inner)::-webkit-outer-spin-button,
.pti-el-input :deep(.el-input__inner)::-webkit-inner-spin-button {
    -webkit-appearance: none !important;
    appearance: none !important;
    margin: 0 !important;
}
.pti-el-input :deep(input[type='number']) {
    -moz-appearance: textfield !important; /* Firefox */
}

/* v28-17: 强制 inner line-height: 30px 跟 placeholder 对齐
   仅 default size — small 让 Element Plus 的小尺寸 token 自己决定 (避免比 el-input-number 高出 9px) */
.pti-wrapper:not(.is-small) .pti-el-input :deep(.el-input__inner) {
    line-height: 30px !important;
    font-size: 13px !important;
}

.pti-select-box {
    /* 宽度由 inline style 控制 */
    min-width: 0;
    box-sizing: border-box;
    display: flex;
    align-items: stretch;
    margin-left: -1px; /* v28-8: 抵消左 wrapper 的 inset shadow 1px, 与右侧左边界对齐 */
    position: relative;
    left: 1px; /* v28-8: 让 select-box 实际边界与左 input 内边界对齐, 视觉无缝 */
}

/* el-select 占满 select-box */
.pti-el-select {
    width: 100%;
}

/* 右 select: 清左半圆角 (左 input 接管), 与 scp-tag-box 视觉一致: padding 1px 11px + 背景 var(--bg-soft) + min-height 33px
   仅 default size — small 让 Element Plus 的 --el-component-size-small token 决定高度, padding 也跟着 el-select__wrapper 默认  */
.pti-wrapper:not(.is-small) .pti-el-select :deep(.el-select__wrapper) {
    border-top-left-radius: 0 !important;
    border-bottom-left-radius: 0 !important;
    border-top-right-radius: var(--el-border-radius-base, 8px) !important;
    border-bottom-right-radius: var(--el-border-radius-base, 8px) !important;
    box-shadow: 0 0 0 1px var(--border-base) inset !important;
    font-size: 13px !important;
    line-height: 30px;
    padding: 1px 11px !important; /* v28-14: 与左 input padding 同, 高度对齐 */
    /* v115: 改走 var(--bg-soft), 暗色模式下不再死白 (与表格斑马纹 --bg-soft 对齐) */
    background: var(--bg-soft) !important;
    min-height: 33px !important; /* v33.1: 与左 input 等高 */
    box-sizing: border-box !important;
    align-items: center !important; /* 文字垂直居中 */
}

.pti-wrapper:not(.is-small) .pti-el-select :deep(.el-select__wrapper.is-hovering),
.pti-wrapper:not(.is-small) .pti-el-select :deep(.el-select__wrapper:hover) {
    box-shadow: 0 0 0 1px var(--el-color-primary-light-5, #c0d4f7) inset !important;
}

.pti-wrapper:not(.is-small) .pti-el-select :deep(.el-select__wrapper.is-focused),
.pti-wrapper:not(.is-small) .pti-el-select :deep(.el-select__wrapper:focus-within) {
    box-shadow: 0 0 0 1px var(--el-color-primary, #409eff) inset !important;
}

/* el-select 下拉框与左 input inner 同字号 (防止 select 字号偏小)
   仅 default size — small 由 el-select__wrapper 自己用 Element Plus 小尺寸 token */
.pti-wrapper:not(.is-small) .pti-el-select :deep(.el-select__placeholder) {
    font-size: 13px !important;
    line-height: 30px !important;
}

/* === small 变体: 跟随 Element Plus --el-component-size-small 高度 ===
   让 PriceTypeInput 与同行的 el-input-number / el-select / el-radio-group 等高
   (default 变体的硬编码值仅 :not(.is-small) 内生效, OrderForm.vue 不受影响) */
.pti-wrapper.is-small .pti-el-select :deep(.el-select__wrapper) {
    border-top-left-radius: 0 !important;
    border-bottom-left-radius: 0 !important;
    border-top-right-radius: var(--el-border-radius-small, 4px) !important;
    border-bottom-right-radius: var(--el-border-radius-small, 4px) !important;
    min-height: var(--el-component-size-small, 24px) !important;
    font-size: var(--el-font-size-small, 12px) !important;
    padding: 1px 8px !important;
    box-sizing: border-box !important;
    align-items: center !important;
    box-shadow: 0 0 0 1px var(--el-border-color, #dcdfe6) inset !important;
    background: var(--el-fill-color-blank, #fff) !important;
}
.pti-wrapper.is-small .pti-el-select :deep(.el-select__wrapper.is-hovering),
.pti-wrapper.is-small .pti-el-select :deep(.el-select__wrapper:hover) {
    box-shadow: 0 0 0 1px var(--el-color-primary-light-5, #c0d4f7) inset !important;
}
.pti-wrapper.is-small .pti-el-select :deep(.el-select__wrapper.is-focused),
.pti-wrapper.is-small .pti-el-select :deep(.el-select__wrapper:focus-within) {
    box-shadow: 0 0 0 1px var(--el-color-primary, #409eff) inset !important;
}
.pti-wrapper.is-small .pti-el-select :deep(.el-select__placeholder) {
    font-size: var(--el-font-size-small, 12px) !important;
    line-height: var(--el-component-size-small, 24px) !important;
}
</style>
