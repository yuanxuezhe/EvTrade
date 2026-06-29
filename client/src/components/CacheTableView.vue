<!--
  CacheTableView.vue — 通用 IDB CRUD 表格组件 (admin-only)

  用途: 浏览/编辑/删除 IndexedDB 4 张业务表 (asset / positions / orders / trades)

  Props:
    storeName: 'asset' | 'positions' | 'orders' | 'trades'
    fields: 字段定义数组 [{key, label, type?, options?, required?, width?, formatter?}]
    title: 页面标题
    keyField: 主键字段名 (默认从 storeName 推, asset=singleton 不支持 add/delete)
    allowAdd: 允许新增行 (默认 true; asset=false)
    allowDelete: 允许删除行 (默认 true; asset=false)
    allowClear: 允许清空整表 (默认 true)
    rowCount: 当前行数 (Prop from parent, 用于 stat-pill)

  Emits:
    refreshed: 表格数据更新后 (携带最新行数)

  操作:
    - 顶部工具栏: 刷新 / 清空 / 新增
    - 表格行: 改 / 删
    - 改 / 增共用 dialog (传入 row=null 即新增, 否则为改)
-->
<template>
  <div class="cache-view fade-in-up" v-loading="loading">
    <!-- 顶部概览 -->
    <section class="stats-row">
      <div class="stat-pill">
        <div class="pill-label">行数</div>
        <div class="pill-value text-mono">{{ rows.length }}</div>
      </div>
      <div class="stat-pill">
        <div class="pill-label">Store</div>
        <div class="pill-value text-mono">{{ storeName }}</div>
      </div>
      <div class="stat-pill">
        <div class="pill-label">Key Field</div>
        <div class="pill-value text-mono">{{ keyField }}</div>
      </div>
    </section>

    <!-- 工具栏 -->
    <div class="content-card filter-bar">
      <div class="filter-left">
        <el-input
          v-model="filterText"
          placeholder="搜索任意字段"
          clearable
          :prefix-icon="Search"
          style="width: 240px"
        />
      </div>
      <div class="filter-right">
        <el-button :icon="Refresh" @click="load" :loading="loading">刷新</el-button>
        <el-button v-if="allowClear" type="warning" :icon="Delete" @click="onClear" plain>清空</el-button>
        <el-button v-if="allowAdd" type="primary" :icon="Plus" @click="openAdd">新增</el-button>
      </div>
    </div>

    <!-- 表格 -->
    <div class="content-card">
      <el-table
        :data="filteredRows"
        stripe
        border
        height="calc(100vh - 360px)"
        empty-text="IDB 中无数据"
      >
        <el-table-column
          v-for="f in fields"
          :key="f.key"
          :prop="f.key"
          :label="displayLabel(f)"
          :width="f.width"
          :formatter="f.formatter"
          show-overflow-tooltip
        />
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openEdit(row)">改</el-button>
            <el-button v-if="allowDelete" size="small" type="danger" @click="onDelete(row)">删</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 改 / 增 dialog -->
    <el-dialog
      v-model="dialogVisible"
      :title="editing ? '编辑' : '新增'"
      width="540px"
      :close-on-click-modal="false"
    >
      <el-form :model="form" label-width="120px">
        <el-form-item
          v-for="f in editableFields"
          :key="f.key"
          :label="displayLabel(f)"
          :required="f.required"
        >
          <!-- enum select -->
          <el-select v-if="f.type === 'select'" v-model="form[f.key]" :disabled="editing && f.key === keyField" style="width: 100%">
            <el-option v-for="o in f.options" :key="o" :label="o" :value="o" />
          </el-select>
          <!-- number -->
          <el-input-number v-else-if="f.type === 'number'" v-model="form[f.key]" :controls="false" style="width: 100%" />
          <!-- readonly key -->
          <el-input v-else-if="editing && f.key === keyField" :model-value="form[f.key]" disabled />
          <!-- text default -->
          <el-input v-else v-model="form[f.key]" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Refresh, Plus, Delete } from '@element-plus/icons-vue'
import { getAll, putItem, deleteItem, clearStore, getItem, countStore } from '../utils/idbStore'

const props = defineProps({
  storeName: { type: String, required: true },
  fields: { type: Array, required: true },
  title: { type: String, default: '' },
  keyField: { type: String, default: null },  // null = auto-detect
  allowAdd: { type: Boolean, default: true },
  allowDelete: { type: Boolean, default: true },
  allowClear: { type: Boolean, default: true },
})
const emit = defineEmits(['refreshed'])

const KEY_DEFAULTS = {
  asset: 'id',
  positions: 'stock_code',
  orders: 'order_no',
  trades: 'trd_date,trade_id',  // 复合键用逗号分隔
}
const _keyField = computed(() => props.keyField || KEY_DEFAULTS[props.storeName] || 'id')

// trades 的 keyField 是复合键, 需要特殊处理: 改 / 删时同时按 [trd_date, trade_id]
const _isComposite = computed(() => _keyField.value.includes(','))

// 单一主键 (singleton 或单字段)
const keyField = computed(() => _isComposite.value ? null : _keyField.value)
// 可编辑字段: 排除 keyField (改时禁用) + 复合键场景下排除 [trd_date, trade_id]
const editableFields = computed(() => {
  if (_isComposite.value) {
    const compositeKeys = _keyField.value.split(',').map(s => s.trim())
    return props.fields.filter(f => !compositeKeys.includes(f.key))
  }
  return props.fields
})

const rows = ref([])
const loading = ref(false)
const saving = ref(false)
const filterText = ref('')
const dialogVisible = ref(false)
const editing = ref(false)  // false=add, true=edit
const form = ref({})

const filteredRows = computed(() => {
  if (!filterText.value) return rows.value
  const k = filterText.value.toLowerCase()
  return rows.value.filter((r) =>
    Object.values(r).some((v) => String(v).toLowerCase().includes(k))
  )
})

/**
 * 列 label 显示: 中文 (英文 key)
 * 让 admin 排查 IDB 数据时, 一眼能看出"这一列对应的是 cash 还是 total_asset"
 * 节省反复对照 server schema 的精力
 */
function displayLabel(f) {
  return `${f.label} (${f.key})`
}

function _emptyForm() {
  const f = {}
  for (const field of props.fields) {
    f[field.key] = field.type === 'number' ? 0 : ''
  }
  return f
}

async function load() {
  loading.value = true
  try {
    rows.value = await getAll(props.storeName)
    emit('refreshed', rows.value.length)
  } catch (e) {
    ElMessage.error(`读取 IDB 失败: ${e.message || e}`)
  } finally {
    loading.value = false
  }
}

function openAdd() {
  editing.value = false
  form.value = _emptyForm()
  dialogVisible.value = true
}

function openEdit(row) {
  editing.value = true
  form.value = { ...row }
  dialogVisible.value = true
}

function _formKey(row) {
  // 返回 IDB put/delete 用的 key: 复合键返回数组, 单键返回标量
  if (_isComposite.value) {
    return _keyField.value.split(',').map(s => row[s.trim()])
  }
  return row[_keyField.value]
}

async function onSave() {
  saving.value = true
  try {
    await putItem(props.storeName, _toPlain(form.value))
    ElMessage.success(editing.value ? '已保存' : '已新增')
    dialogVisible.value = false
    await load()
  } catch (e) {
    ElMessage.error(`保存失败: ${e.message || e}`)
  } finally {
    saving.value = false
  }
}

async function onDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确认删除 ${_keyField.value} = ${_formKey(row)} ?`,
      '删除确认',
      { type: 'warning' }
    )
  } catch {
    return  // 用户取消
  }
  try {
    const key = _formKey(row)
    await deleteItem(props.storeName, key)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(`删除失败: ${e.message || e}`)
  }
}

async function onClear() {
  try {
    await ElMessageBox.confirm(
      `确认清空 ${props.storeName} 表? 刷新页面后会从 server 重新灌入`,
      '清空确认',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await clearStore(props.storeName)
    ElMessage.success('已清空')
    await load()
  } catch (e) {
    ElMessage.error(`清空失败: ${e.message || e}`)
  }
}

function _toPlain(value) {
  if (value === null || value === undefined) return value
  if (typeof value !== 'object') return value
  return JSON.parse(JSON.stringify(value))
}

onMounted(load)
</script>

<style scoped>
.cache-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}
.stats-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-3);
}
.stat-pill {
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.pill-label {
  font-size: 12px;
  color: var(--text-secondary);
}
.pill-value {
  font-size: 18px;
  font-weight: 700;
}
.text-mono {
  font-family: var(--font-mono, 'JetBrains Mono', 'Consolas', monospace);
}
</style>
