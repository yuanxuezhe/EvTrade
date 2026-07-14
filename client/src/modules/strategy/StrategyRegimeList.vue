<!--
  StrategyRegimeList.vue — regime collapse 列表（task 11.8 拆文件保 ≤ 250 行）

  Props：
    regimes - StrategyRegime[]（regime + 嵌套 grids）
-->
<template>
  <div class="regime-list" data-el="regime-list">
    <el-empty
      v-if="!regimes?.length"
      description="暂无 regime 配置"
      :image-size="60"
    />
    <el-collapse v-else accordion data-el="monitor-regimes">
      <el-collapse-item
        v-for="r in regimes"
        :key="r.id"
        :name="r.id"
        :data-el="'monitor-regime-' + r.id"
      >
        <template #title>
          <span class="rl-title">
            <el-tag v-if="!r.enabled" size="small" type="info">停用</el-tag>
            <span>{{ r.name }}</span>
            <span class="rl-pri">优先级 {{ r.priority }}</span>
          </span>
        </template>
        <div class="rl-body">
          <div class="rl-flags">
            <span class="rl-flags-label">需要：</span>
            <el-tag
              v-for="code in r.required_flags"
              :key="'req-' + code"
              size="small"
              type="primary"
              class="rl-flag-tag"
            >
              {{ code }}
            </el-tag>
            <span class="rl-flags-label rl-flags-spacer">排除：</span>
            <el-tag
              v-for="code in r.exclude_flags"
              :key="'exc-' + code"
              size="small"
              type="info"
              class="rl-flag-tag"
            >
              {{ code }}
            </el-tag>
            <el-tag v-if="r.clear_position" size="small" type="danger">触发清仓</el-tag>
          </div>
          <el-table
            :data="r.grids || []"
            size="small"
            :show-overflow-tooltip="true"
            class="rl-grid-table"
          >
            <el-table-column label="方向" width="100">
              <template #default="{ row }">
                <span :class="['rl-dir-chip', row.direction]">
                  {{ row.direction === 'buy' ? '买' : '卖' }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="触发价" width="100" align="right">
              <template #default="{ row }">
                <span class="text-mono">{{ row.trigger_price.toFixed(3) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="量" width="100" align="right">
              <template #default="{ row }">
                <span class="text-mono">{{ row.volume }}</span>
              </template>
            </el-table-column>
            <el-table-column label="已触发/上限" width="100" align="center">
              <template #default="{ row }">
                {{ row.fired_count || 0 }} / {{ row.max_fires ?? '∞' }}
              </template>
            </el-table-column>
            <el-table-column label="启用" width="100">
              <template #default="{ row }">
                <el-tag v-if="row.enabled === false" size="small" type="info">停用</el-tag>
                <el-tag v-else size="small" type="success">启用</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="优先级" width="100" align="right">
              <template #default="{ row }">
                <span class="text-mono">{{ row.priority }}</span>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<script setup>
defineProps({
  regimes: { type: Array, default: () => [] },
})
</script>

<style scoped>
.regime-list {
  width: 100%;
}
.rl-title {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}
.rl-pri {
  color: var(--text-placeholder);
  font-size: 12px;
  margin-left: var(--space-2);
}
.rl-body {
  padding: var(--space-2) 0;
}
.rl-flags {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-1);
  margin-bottom: var(--space-2);
}
.rl-flags-label {
  font-size: 12px;
  color: var(--text-secondary);
}
.rl-flags-spacer {
  margin-left: var(--space-3);
}
.rl-flag-tag {
  font-family: var(--font-mono);
}
.rl-dir-chip {
  display: inline-block;
  padding: 1px 8px;
  border-radius: var(--radius-full);
  font-size: 12px;
  font-weight: 600;
}
.rl-dir-chip.buy {
  background: var(--color-up-bg);
  color: var(--color-up);
}
.rl-dir-chip.sell {
  background: var(--color-down-bg);
  color: var(--color-down);
}
</style>