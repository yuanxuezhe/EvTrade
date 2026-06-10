<template>
  <div ref="chartEl" class="chart-container" :style="{ height: height }"></div>
</template>

<script setup>
import { onMounted, onUnmounted, ref, watch, shallowRef } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart, BarChart, PieChart } from 'echarts/charts'
import {
  TitleComponent, TooltipComponent, GridComponent, LegendComponent,
  DataZoomComponent
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useUiStore } from '../stores/ui'

echarts.use([
  LineChart, BarChart, PieChart,
  TitleComponent, TooltipComponent, GridComponent, LegendComponent, DataZoomComponent,
  CanvasRenderer
])

const props = defineProps({
  option: { type: Object, required: true },
  height: { type: String, default: '320px' }
})

const chartEl = ref(null)
const chart = shallowRef(null)
const uiStore = useUiStore()

function init() {
  if (!chartEl.value) return
  const theme = uiStore.theme === 'dark' ? 'dark' : null
  if (chart.value) {
    chart.value.dispose()
  }
  chart.value = echarts.init(chartEl.value, theme)
  chart.value.setOption(props.option, true)
}

function handleResize() {
  chart.value?.resize()
}

onMounted(() => {
  init()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  chart.value?.dispose()
})

watch(() => props.option, (val) => {
  chart.value?.setOption(val, true)
}, { deep: true })

watch(() => uiStore.theme, () => {
  init()
})
</script>

<style scoped>
.chart-container {
  width: 100%;
}
</style>
