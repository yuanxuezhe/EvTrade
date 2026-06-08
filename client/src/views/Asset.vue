<template>
  <div class="asset-page">
    <h2>账户资金</h2>

    <el-card class="asset-card">
      <el-descriptions :column="2" border>
        <el-descriptions-item label="可用资金">
          <span class="asset-value">¥{{ assetStore.asset.cash.toFixed(2) }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="冻结资金">
          <span class="asset-value">¥{{ assetStore.asset.frozen_cash.toFixed(2) }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="持仓市值">
          <span class="asset-value">¥{{ assetStore.asset.market_value.toFixed(2) }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="总资产">
          <span class="asset-value total">¥{{ assetStore.asset.total_asset.toFixed(2) }}</span>
        </el-descriptions-item>
      </el-descriptions>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useAssetStore } from '../stores/asset'

const assetStore = useAssetStore()

onMounted(async () => {
  await assetStore.fetchAsset()
})
</script>

<style scoped>
.asset-page {
  max-width: 800px;
}
.asset-value {
  font-size: 18px;
  font-weight: 500;
}
.asset-value.total {
  color: #409eff;
  font-size: 22px;
}
</style>