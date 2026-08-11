<!--
  StrategyOrderCreatePanel.vue — 策略下单创建母单 (v126, 子组件)

  顶部策略下拉 (仅含 best_params 已回测出的) + 「创建母单」按钮
  策略 store 已含 best_params (v123 落库); 无 best_params 灰置按钮
-->
<template>
  <el-card shadow="never" class="so-create-card" data-el="so-create-card">
    <template #header>
      <div class="so-card-head">
        <span>策略下单</span>
        <span class="so-card-sub">从已回测策略建母单</span>
      </div>
    </template>
    <div class="so-create-row">
      <el-select
        v-model="selectedStrategyId"
        placeholder="选择策略 (需已回测出最佳参数)"
        filterable
        :loading="loading"
        style="width: 320px"
        data-el="so-strategy-select"
        @change="onStrategyChange"
      >
        <el-option
          v-for="s in backtestedStrategies"
          :key="s.strategy_id"
          :value="s.strategy_id"
          :label="`${s.name} · ${s.stock_code}`"
        />
      </el-select>
      <el-tag v-if="selectedStrategy" size="small" type="info" effect="plain">
        标的 {{ selectedStrategy.stock_code }}
      </el-tag>
      <el-button
        type="primary"
        :disabled="!selectedStrategy || selectedStrategy.user_id !== currentUserId"
        :loading="submitting"
        data-el="so-create-btn"
        @click="onCreate"
      >
        创建母单
      </el-button>
    </div>
  </el-card>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { scriptStrategyApi } from '../../api/script_strategy'
import { useAuthStore } from '../../stores/auth'

const emit = defineEmits(['created'])

const auth = useAuthStore()
const loading = ref(false)
const currentUserId = computed(() => auth.user?.id)

const strategies = ref([])
const selectedStrategyId = ref(null)
const submitting = ref(false)

// 已回测出 best_params 的策略 (本人才可建母单)
const backtestedStrategies = computed(() => {
  return strategies.value.filter(
    s => s.best_params && Object.keys(s.best_params).length > 0
  )
})

const selectedStrategy = computed(() => {
  if (!selectedStrategyId.value) return null
  return backtestedStrategies.value.find(
    s => s.strategy_id === selectedStrategyId.value
  ) || null
})

async function loadStrategies() {
  loading.value = true
  try {
    strategies.value = (await scriptStrategyApi.listStrategies()) || []
  } catch (e) {
    ElMessage.error(`加载策略失败: ${e?.response?.data?.detail?.msg || e.message}`)
  } finally {
    loading.value = false
  }
}

function onStrategyChange() {
  // 留 hook (未来标的联动行情面板可加)
}

async function onCreate() {
  if (!selectedStrategy.value) return
  submitting.value = true
  try {
    const r = await scriptStrategyApi.createStrategyOrder(selectedStrategy.value.strategy_id)
    ElMessage.success(`母单 #${r.task_id} 已创建`)
    selectedStrategyId.value = null
    emit('created', r)
  } catch (e) {
    ElMessage.error(`建母单失败: ${e?.response?.data?.detail?.msg || e.message}`)
  } finally {
    submitting.value = false
  }
}

onMounted(loadStrategies)

defineExpose({ reload: loadStrategies })
</script>
