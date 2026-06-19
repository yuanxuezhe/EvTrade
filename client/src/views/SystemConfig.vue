<template>
  <div class="system-config fade-in-up">
    <!-- 对账配置 -->
    <el-card class="config-card" shadow="hover">
      <template #header>
        <span class="card-title">🔁 对账配置</span>
      </template>
      <el-form :model="reconcileCfg" label-width="160px" v-loading="loading.config">
        <el-form-item label="自动对账">
          <el-switch v-model="reconcileCfg.auto_reconcile" />
          <span class="hint">日初时自动调柜台对账</span>
        </el-form-item>
        <el-form-item label="自动时以谁为准">
          <el-radio-group v-model="reconcileCfg.auto_use_broker_data">
            <el-radio :value="1">以柜台为准</el-radio>
            <el-radio :value="0">以本地为准</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading.savingReconcile" @click="saveReconcile">
            保存
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 交易时段配置 -->
    <el-card class="config-card" shadow="hover">
      <template #header>
        <span class="card-title">🕒 交易时段配置</span>
      </template>
      <el-form :model="sessionCfg" label-width="160px" v-loading="loading.config">
        <el-form-item label="上午时段">
          <el-time-picker v-model="sessionCfg.morning_start" format="HH:mm" placeholder="开始" />
          <span style="margin: 0 8px">—</span>
          <el-time-picker v-model="sessionCfg.morning_end" format="HH:mm" placeholder="结束" />
        </el-form-item>
        <el-form-item label="下午时段">
          <el-time-picker v-model="sessionCfg.afternoon_start" format="HH:mm" placeholder="开始" />
          <span style="margin: 0 8px">—</span>
          <el-time-picker v-model="sessionCfg.afternoon_end" format="HH:mm" placeholder="结束" />
        </el-form-item>
        <el-form-item label="半日市">
          <el-switch v-model="sessionCfg.is_half_day" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading.savingSession" @click="saveSession">
            保存
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 费率配置 -->
    <el-card class="config-card" shadow="hover">
      <template #header>
        <span class="card-title">💰 费率配置</span>
      </template>
      <el-form :model="feeCfg" label-width="160px" v-loading="loading.config">
        <el-form-item label="佣金费率">
          <el-input-number
            v-model="feeCfg.commission_rate"
            :step="0.00001"
            :min="0"
            :max="0.01"
            :precision="5"
          />
          <span class="hint">万一 = 0.0001</span>
        </el-form-item>
        <el-form-item label="印花税率">
          <el-input-number
            v-model="feeCfg.stamp_tax_rate"
            :step="0.0001"
            :min="0"
            :max="0.01"
            :precision="4"
          />
          <span class="hint">默认 0.001 (卖出)</span>
        </el-form-item>
        <el-form-item label="滑点">
          <el-input-number
            v-model="feeCfg.slippage"
            :step="0.0001"
            :min="0"
            :max="0.01"
            :precision="4"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading.savingFee" @click="saveFee">
            保存
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { reconcileApi, sessionApi, feeConfigApi } from '../api/admin'

// 'HH:mm:ss' -> Date (el-time-picker v-model 期望 Date)
function _t2d(s) {
  if (!s) return null
  if (s instanceof Date) return s
  const [h, m, sec = 0] = String(s).split(':').map(Number)
  const d = new Date(2000, 0, 1, h, m, sec)
  return isNaN(d.getTime()) ? null : d
}
// Date -> 'HH:mm:ss'
function _d2t(d) {
  if (!d) return null
  const h = String(d.getHours()).padStart(2, '0')
  const m = String(d.getMinutes()).padStart(2, '0')
  const s = String(d.getSeconds()).padStart(2, '0')
  return `${h}:${m}:${s}`
}

const loading = reactive({
  config: false,
  savingReconcile: false,
  savingSession: false,
  savingFee: false,
})

const reconcileCfg = reactive({ auto_reconcile: true, auto_use_broker_data: 1 })
const sessionCfg = reactive({
  morning_start: _t2d('09:15:00'), morning_end: _t2d('11:30:00'),
  afternoon_start: _t2d('13:00:00'), afternoon_end: _t2d('15:00:00'),
  is_half_day: false
})
const feeCfg = reactive({ commission_rate: 0.0001, stamp_tax_rate: 0.001, slippage: 0 })

async function loadConfig() {
  loading.config = true
  try {
    const [rc, sc, fc] = await Promise.all([
      reconcileApi.getConfig(),
      sessionApi.get(),
      feeConfigApi.get()
    ])
    Object.assign(reconcileCfg, rc)
    sessionCfg.morning_start = _t2d(sc.morning_start)
    sessionCfg.morning_end = _t2d(sc.morning_end)
    sessionCfg.afternoon_start = _t2d(sc.afternoon_start)
    sessionCfg.afternoon_end = _t2d(sc.afternoon_end)
    sessionCfg.is_half_day = sc.is_half_day
    Object.assign(feeCfg, fc)
  } catch (e) {
    ElMessage.error('配置加载失败')
  } finally {
    loading.config = false
  }
}

async function saveReconcile() {
  loading.savingReconcile = true
  try { await reconcileApi.updateConfig(reconcileCfg); ElMessage.success('对账配置已保存') }
  catch { ElMessage.error('保存失败') }
  finally { loading.savingReconcile = false }
}
async function saveSession() {
  loading.savingSession = true
  try {
    await sessionApi.update({
      morning_start: _d2t(sessionCfg.morning_start),
      morning_end: _d2t(sessionCfg.morning_end),
      afternoon_start: _d2t(sessionCfg.afternoon_start),
      afternoon_end: _d2t(sessionCfg.afternoon_end),
      is_half_day: sessionCfg.is_half_day,
    })
    ElMessage.success('时段配置已保存')
  }
  catch { ElMessage.error('保存失败') }
  finally { loading.savingSession = false }
}
async function saveFee() {
  loading.savingFee = true
  try { await feeConfigApi.update(feeCfg); ElMessage.success('费率已保存') }
  catch { ElMessage.error('保存失败') }
  finally { loading.savingFee = false }
}

onMounted(() => {
  loadConfig()
})
</script>

<style scoped>
.system-config { padding: 16px; }
.config-card { margin-bottom: 16px; }
.card-title { font-weight: 600; }
.hint { color: #909399; font-size: 12px; margin-left: 8px; }
</style>
