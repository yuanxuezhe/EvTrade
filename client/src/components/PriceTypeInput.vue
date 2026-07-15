<!--
  PriceTypeInput.vue — 委托价格 + 价格类型 组合组件

  与 StockCodePicker 对称:
  - 左 50%  : el-input-number (价格)
  - 右 50%  : el-select (限价/最新价/市价)
  - 默认    : PriceType.FIX_PRICE (限价)
  - 50/50  : 与 StockCodePicker 一致

  v__: 价格类型与 xtconstant 柜台协议 1:1 对齐
    0 = xtconstant.FIX_PRICE                 (限价 / 指定价)
    1 = xtconstant.LATEST_PRICE              (最新价)
    2 = xtconstant.MARKET_PEER_PRICE_FIRST   (市价 / 对手方最优价)
-->
<template>
  <div class="price-type-input">
    <div class="pti-half pti-price">
      <el-input-number
        v-model="localPrice"
        :min="0"
        :max="999999"
        :precision="2"
        :step="0.01"
        :disabled="disabled"
        size="small"
        controls-position="right"
        class="pti-input"
        :placeholder="placeholderText"
      />
    </div>
    <div class="pti-half pti-type">
      <el-select
        v-model="localPriceType"
        size="small"
        :disabled="disabled"
        class="pti-select"
        :teleported="false"
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
import { PriceType, priceTypeOptions } from '@/constants/priceType.js'

const props = defineProps({
  price: { type: [Number, String], default: null },
  priceType: { type: Number, default: PriceType.FIX_PRICE },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['update:price', 'update:priceType'])

// ---- 受控双向绑定（与 OrderForm 的 v-model:price / v-model:priceType 对称） ----
const localPrice = computed({
  get: () => props.price,
  set: (v) => emit('update:price', v),
})

const localPriceType = computed({
  get: () => props.priceType,
  set: (v) => emit('update:priceType', v),
})

// ---- placeholder 切换：限价 → "输入价格"；其他 → 行情价 / 卖一价（不输入） ----
const placeholderText = computed(() =>
  props.priceType === PriceType.FIX_PRICE ? '输入价格' : '行情价(自动)'
)
</script>

<style scoped>
/* === 两段贴一起组合 (scp→pti 前缀, 复用 v28 实证样式) === */
.price-type-input {
  display: flex;
  align-items: stretch;
  gap: 0;
  width: 100%;
  height: 32px;             /* 与 StockCodePicker 同高 */
  line-height: 32px;
}

.pti-half {
  display: flex;
  align-items: center;
  min-width: 0;
}

.pti-price { width: 50%; }
.pti-type  { width: 50%; }

/* === 关键：左半段的 input right-border 取消，让两段无缝贴一起 === */
.pti-price :deep(.el-input-number),
.pti-price :deep(.el-input__wrapper),
.pti-price :deep(.el-input-number__decrease),
.pti-price :deep(.el-input-number__increase) {
  border-top-left-radius: 4px;
  border-bottom-left-radius: 4px;
}

/* === 右半段 select：左上 / 左下直角（贴一起），右上 / 右下圆角 === */
.pti-type :deep(.el-select),
.pti-type :deep(.el-select .el-input),
.pti-type :deep(.el-select .el-input__wrapper),
.pti-type :deep(.el-select__wrapper) {
  border-top-left-radius: 0;
  border-bottom-left-radius: 0;
  border-top-right-radius: 4px;
  border-bottom-right-radius: 4px;
}

/* === 让两段中间也有 border-right: none 在左段 === */
.pti-price :deep(.el-input-number) .el-input__wrapper {
  border-right: 0;
}

.pti-type :deep(.el-select__wrapper) {
  border-left: 0;
}

/* === 高度统一 === */
.pti-input :deep(.el-input-number),
.pti-select :deep(.el-select) {
  width: 100%;
  height: 32px;
}

.pti-input :deep(.el-input-number .el-input__inner) {
  height: 30px;
  line-height: 30px;
}

.pti-select :deep(.el-select__wrapper) {
  height: 30px;
  line-height: 30px;
}

/* === 防小尺寸下边框错位：line-height baseline 修复 === */
.pti-input :deep(.el-input-number__decrease),
.pti-input :deep(.el-input-number__increase) {
  line-height: 30px;
  height: 30px;
  box-sizing: border-box;
}

.pti-input :deep(.el-input-number__decrease),
.pti-input :deep(.el-input-number__increase) {
  border-top-color: var(--el-border-color);
  border-bottom-color: var(--el-border-color);
}

.pti-input :deep(.el-input-number__decrease) {
  border-left-color: var(--el-border-color);
}

.pti-input :deep(.el-input-number__increase) {
  border-right-color: var(--el-border-color);
}
</style>
