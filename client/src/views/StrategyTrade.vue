<!--
  StrategyTrade.vue — 策略交易主视图（task 12）

  业务逻辑拆分到 useStrategyTrade.js（composable）
  视图布局：左侧 StrategyList + 表单 / 右侧 StrategyMonitor
-->
<template>
  <div class="strat-trade-view fade-in-up" data-el="strategy-trade-view">
    <header class="st-header">
      <el-tabs v-model="activeTab" class="st-tabs" data-el="strategy-trade-tab">
        <el-tab-pane
          v-for="tab in TABS"
          :key="tab.key"
          :name="tab.key"
          :data-el="'tab-' + tab.key"
        >
          <template #label>
            <span>{{ tab.label }}</span>
            <el-badge
              v-if="getTabCount(tab.key) > 0"
              :value="getTabCount(tab.key)"
              :max="99"
              class="st-badge"
            />
          </template>
        </el-tab-pane>
      </el-tabs>
      <div class="st-actions">
        <el-button
          type="primary"
          :icon="Plus"
          :disabled="!!selectedId"
          @click="onCreate"
          data-el="strategy-trade-create"
        >
          新建策略
        </el-button>
        <el-button
          v-if="selectedId"
          type="danger"
          :icon="Delete"
          :loading="deleting"
          @click="onDelete"
          data-el="strategy-trade-delete"
        >
          删除
        </el-button>
      </div>
    </header>

    <div v-if="loading" v-loading="true" class="st-loading" />

    <div v-else class="st-body">
      <section class="st-pane st-pane-left">
        <StrategyList
          :strategies="currentStrategies"
          :selected-id="selectedId"
          @select="onSelect"
        />

        <div v-if="drafting" class="st-draft">
          <h4 class="st-section-title">新建策略（draft）</h4>
          <StrategyConfig v-model="draft" />
          <h4 class="st-section-title">参数集</h4>
          <RegimeEditor
            v-for="(r, idx) in draft.regimes"
            :key="r.id || `draft-r-${idx}`"
            v-model="draft.regimes[idx]"
            :data-el-prefix="'draft-regime-' + idx"
            @remove="draft.regimes.splice(idx, 1)"
            @add-grid="onAddGrid(idx)"
          />
          <el-button
            type="primary"
            plain
            :icon="Plus"
            @click="onAddRegime('draft')"
            data-el="draft-add-regime"
          >
            新增 regime
          </el-button>
          <div class="st-form-actions">
            <el-button @click="cancelDraft">取消</el-button>
            <el-button
              type="primary"
              :loading="creating"
              @click="onSubmit"
              data-el="strategy-trade-submit"
            >
              创建
            </el-button>
          </div>
        </div>

        <div v-else-if="currentStrategy" class="st-edit">
          <h4 class="st-section-title">策略信息</h4>
          <StrategyConfig v-model="currentStrategy" />
          <h4 class="st-section-title">参数集（{{ currentStrategy.regimes?.length || 0 }}）</h4>
          <RegimeEditor
            v-for="(r, idx) in currentStrategy.regimes"
            :key="r.id"
            v-model="currentStrategy.regimes[idx]"
            :data-el-prefix="'regime-' + r.id"
            @remove="onRemoveRegime(idx)"
            @add-grid="onAddGrid(idx)"
          />
          <el-button
            type="primary"
            plain
            :icon="Plus"
            @click="onAddRegime('existing')"
            data-el="strategy-trade-add-regime"
          >
            新增 regime
          </el-button>
          <div class="st-form-actions">
            <el-button
              type="primary"
              :loading="saving"
              @click="onSave"
              data-el="strategy-trade-save"
            >
              保存修改
            </el-button>
          </div>
        </div>

        <el-empty
          v-else
          description="选中左侧策略，或点击「新建策略」"
          :image-size="80"
        />
      </section>

      <section class="st-pane st-pane-right">
        <StrategyMonitor
          v-if="currentStrategy"
          :strategy="currentStrategy"
          :current-trd-date="currentTrdDate"
        />
        <el-empty v-else description="请选择策略" :image-size="100" />
      </section>
    </div>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { Plus, Delete } from '@element-plus/icons-vue'
import { useStrategyStore } from '../stores/strategy'
import StrategyList from '../components/strategy/StrategyList.vue'
import StrategyConfig from '../modules/strategy/StrategyConfig.vue'
import RegimeEditor from '../modules/strategy/RegimeEditor.vue'
import StrategyMonitor from '../modules/strategy/StrategyMonitor.vue'
import { useStrategyTrade } from './useStrategyTrade'

const {
  TABS, activeTab, selectedId, drafting, draft,
  creating, saving, deleting,
  loading, currentTrdDate, currentStrategies, currentStrategy,
  getTabCount,
  onSelect, onCreate, cancelDraft, onSubmit, onSave, onDelete,
  onAddRegime, onRemoveRegime, onAddGrid,
} = useStrategyTrade()

const store = useStrategyStore()

onMounted(async () => {
  try {
    await store.loadStrategies()
    await store.loadFlagDefinitions()
  } catch (_) { /* 灰度门 503 等, UI 提示已存于 store.error */ }
})
</script>

<style scoped>
.strat-trade-view {
  display: flex;
  flex-direction: column;
  height: calc(100vh - var(--header-height) - var(--space-4) * 2);
  padding: var(--space-4);
  gap: var(--space-3);
}
.st-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-3);
}
.st-tabs { flex: 1; }
.st-badge { margin-left: var(--space-1); }
.st-actions { display: flex; gap: var(--space-2); }
.st-loading {
  flex: 1;
  display: grid;
  place-items: center;
}
.st-body {
  flex: 1;
  display: grid;
  grid-template-columns: minmax(360px, 1fr) minmax(420px, 2fr);
  gap: var(--space-3);
  overflow: hidden;
}
.st-pane {
  overflow-y: auto;
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-base);
  padding: var(--space-3);
}
.st-pane-left {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.st-section-title {
  font-size: 13px;
  font-weight: 600;
  margin: var(--space-2) 0;
  color: var(--text-primary);
}
.st-form-actions {
  margin-top: var(--space-3);
  display: flex;
  gap: var(--space-2);
  justify-content: flex-end;
}
</style>