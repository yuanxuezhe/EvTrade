<!--
  StockTargetCell.vue — 通用 cell: 证券代码 + 名称 (+ T0 徽章) (change stock-target-cell-unify)

  设计目标:
    - 单一职责: 渲染一只证券的"代码 + 名称"组合 (含 T+0 支持闪电徽章)
    - 全站统一: 替代 10+ 处表格里手写的 <span class="text-mono tp-stock-code">…</span>+
               <span class="text-secondary" v-t0-badge>…</span> 模板
    - 数据源: useStocksStore.stockName(code) 走 IDB 缓存 (O(1) Map.get, 已 cacheLoaded 自动追踪)
    - T0 徽章: v-t0-badge 全局指令 (复用, 不再重复挂 DOM)
    - 风格: 与原模板完全一致 — code=mono+primary 视觉靠 main.css 的 .tp-stock-code,
            名称 text-secondary + 6px 间距 + v-t0-badge 紧贴名称右侧

  Props:
    stockCode  String   必填, 证券代码 (如 '600519.SH')
    codeProp    String   可选, 备用 prop 名 (模板里取 row.xxx_code 这种动态字段的场景, 如 'pool.stock_code')
                          不传时默认走 stockCode prop
    showName    Boolean  默认 true, 是否显示名称 + 6px 间距 + T0 徽章
                         false 时只渲染代码 span (等同原 <span class="text-mono tp-stock-code">)
    size        String   可选 'default' | 'small', 默认 default (与表格字体一致)
                         small 时整体字体 12px (适用于密集表格, 如 StkPool 批量添加弹窗)

  用法 (模板):
    1. 标准 (row.stock_code + 默认名称):
       <StockTargetCell :stock-code="row.stock_code" />

    2. 只显示代码 (无名称, 含 T0 徽章):
       <StockTargetCell :stock-code="row.stock_code" :show-name="false" />

    3. small 模式 (密集表格):
       <StockTargetCell :stock-code="row.stock_code" size="small" />

    4. 自定义字段名 (兼容历史 row.xxx_code 这种):
       <StockTargetCell :stock-code="row.code || row.stock_code" />

  内部小细节:
    - name 为 null (cache 未加载 / code 找不到) 时显示 '—', 与原模板兜底一致
    - 'text-mono' / 'tp-stock-code' / 'text-secondary' 类名直接由 main.css 提供,
      避免本组件再加 scoped CSS 与全局类冲突
    - v-t0-badge 是全局指令, cacheLoaded=false 时不会渲染徽章 (内部有 cache-ready watcher 兜底)
-->
<template>
  <span class="stc-wrap" :class="size === 'small' ? 'stc-small' : ''">
    <span class="text-mono tp-stock-code">{{ stockCode }}</span>
    <template v-if="showName">
      <span
        class="text-secondary"
        style="margin-left: 6px"
        v-t0-badge="stockCode"
      >
        {{ name || '—' }}
      </span>
    </template>
  </span>
</template>

<script setup>
import { computed } from 'vue'
import { useStocksStore } from '../../stores/stocks'

const props = defineProps({
  stockCode: { type: String, default: '' },
  showName: { type: Boolean, default: true },
  size: { type: String, default: 'default' },
})

const stocksStore = useStocksStore()

// useStocksStore.stockName(code) 内部已:
//   - 拦截 null/empty → null
//   - 读 cacheLoaded, 未加载 → null (vue 响应式自动追踪)
//   - 走 reactive Map.get O(1)
// 计算属性缓存, 避免模板每渲染都走函数调用
const name = computed(() => stocksStore.stockName(props.stockCode))
</script>

<style scoped>
/* wrap 仅做 small 字号缩放 — 其它样式 (code/名称/T0 徽章) 走 main.css 全局类
   避免与全局 .tp-stock-code / .text-secondary / .t0-badge 重名导致 scoped 隔离 */
.stc-wrap {
  display: inline-flex;
  align-items: baseline;
}
.stc-small {
  font-size: 12px;
}
</style>
