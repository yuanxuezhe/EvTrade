<!--
  CacheTableView.vue — 通用 Pinia CRUD 表格组件 (admin-only, 调试用)

  用途: 直接读写业务 Pinia store ref (e.g. holdingsStore.positions)
        改动通过 Vue 响应式自动传播到业务页面, 无需 IDB 持久化

  Props:
    rowsRef: 响应式 ref (array 或 object), 直接改这一份 = 改业务数据
    keyField: 主键字段名 ('id' / 'stock_code' / 'order_no' / 'trd_date,trade_id' 复合键)
    fields: 字段定义数组 [{key, label, type?, options?, required?, width?}]
    title: 页面标题
    allowAdd: 允许新增行 (默认 true; asset=false)
    allowDelete: 允许删除行 (默认 true; asset=false)
    allowClear: 允许清空整表 (默认 true)
-->
<template>
  <div class="cache-view fade-in-up" v-loading="loading">
    <!-- 顶部概览 -->
    <section class="stats-row">
      <div class="stat-pill">
        <div class="pill-label">行数</div>
        <div class="pill-value text-mono">{{ rowsLength }}</div>
      </div>
      <div class="stat-pill">
        <div class="pill-label">Key Field</div>
        <div class="pill-value text-mono">{{ keyField }}</div>
      </div>
      <div class="stat-pill">
        <div class="pill-label">Data Source</div>
        <div class="pill-value text-mono">Pinia</div>
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
        <el-button v-if="allowAdd" type="primary" :icon="Plus" @click="openAdd">新增</el-button>
        <el-button v-if="allowClear" type="warning" :icon="Delete" @click="onClear" plain>清空</el-button>
      </div>
    </div>

    <!-- 表格 -->
    <div class="content-card table-with-pagination">
      <el-table
        :data="pagedRows"
        stripe
        border
        height="calc(100vh - 360px)"
        empty-text="数据为空 (Pinia 内存)"
        @sort-change="onSortChange"
      >
        <el-table-column
          v-for="f in fields"
          :key="f.key"
          :prop="f.key"
          :label="displayLabel(f)"
          :min-width="f.width"
          :formatter="f.formatter"
          :header-cell-style="{ whiteSpace: 'nowrap' }"
          :sortable="f.type !== 'object' && f.type !== 'array' ? 'custom' : false"
          show-overflow-tooltip
        />
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openEdit(row)">改</el-button>
            <el-button v-if="allowDelete" size="small" type="danger" @click="onDelete(row)">删</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="filteredRows.length > pageSize" class="dtv-pagination">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="filteredRows.length"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          size="small"
          background
        />
      </div>
    </div>

    <!-- 改 / 增 dialog -->
    <el-dialog
      v-model="dialogVisible"
      :title="editing ? '编辑' : '新增'"
      width="540px"
      :close-on-click-modal="false"
    >
      <el-form :model="form" label-width="140px">
        <el-form-item
          v-for="f in editableFields"
          :key="f.key"
          :label="displayLabel(f)"
          :required="f.required"
        >
          <el-select v-if="f.type === 'select'" v-model="form[f.key]" :disabled="editing && f.key === keyField" style="width: 100%">
            <el-option v-for="o in f.options" :key="o" :label="o" :value="o" />
          </el-select>
          <el-input-number v-else-if="f.type === 'number'" v-model="form[f.key]" :controls="false" style="width: 100%" />
          <el-input v-else-if="editing && f.key === keyField" :model-value="form[f.key]" disabled />
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
import { ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Plus, Delete } from '@element-plus/icons-vue'

const props = defineProps({
  // 必填: 业务数据 ref (e.g. useHoldingsStore().positions)
  //   - 数组类型 (positions / orders / trades): rowsRef.value 是 array
  //   - 对象类型 (asset): rowsRef.value 是 object, keyField='id'
  rowsRef: { type: [Array, Object], required: true },
  keyField: { type: String, required: true },
  fields: { type: Array, required: true },
  title: { type: String, default: '' },
  allowAdd: { type: Boolean, default: true },
  allowDelete: { type: Boolean, default: true },
  allowClear: { type: Boolean, default: true },
})

// 单一主键 vs 复合键 ('trd_date,trade_id' -> ['trd_date', 'trade_id'])
const _isComposite = computed(() => props.keyField.includes(','))
const _keyParts = computed(() =>
  _isComposite.value ? props.keyField.split(',').map(s => s.trim()) : [props.keyField]
)
const editableFields = computed(() => {
  if (_isComposite.value) {
    return props.fields.filter(f => !_keyParts.value.includes(f.key))
  }
  return props.fields.filter(f => f.key !== props.keyField)
})

// 表格显示: 数组模式 / 对象模式
const isObjectMode = computed(() => !Array.isArray(props.rowsRef))
const rows = computed(() => {
  if (isObjectMode.value) {
    // asset: 单行对象 -> 包成 1 行数组
    return Object.keys(props.rowsRef).length > 0 ? [props.rowsRef] : []
  }
  return props.rowsRef || []
})
const rowsLength = computed(() => rows.value.length)

const loading = ref(false)
const saving = ref(false)
const filterText = ref('')
const dialogVisible = ref(false)
const editing = ref(false)
const form = ref({})

const filteredRows = computed(() => {
  if (!filterText.value) return rows.value
  const k = filterText.value.toLowerCase()
  return rows.value.filter((r) =>
    Object.values(r).some((v) => String(v).toLowerCase().includes(k))
  )
})

// 排序
const sortProp = ref('')
const sortOrder = ref('')
const sortedRows = computed(() => {
  if (!sortProp.value || !sortOrder.value) return filteredRows.value
  const prop = sortProp.value
  const dir = sortOrder.value === 'ascending' ? 1 : -1
  return [...filteredRows.value].sort((a, b) => {
    const va = a[prop] ?? ''
    const vb = b[prop] ?? ''
    if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * dir
    return String(va).localeCompare(String(vb)) * dir
  })
})

function onSortChange({ prop: p, order }) {
  sortProp.value = p || ''
  sortOrder.value = order || ''
  page.value = 1
}

// 分页
const page = ref(1)
const pageSize = ref(20)
const pagedRows = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return sortedRows.value.slice(start, start + pageSize.value)
})

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

function _rowKey(row) {
  if (_isComposite.value) {
    return _keyParts.value.map(k => row[k])
  }
  return row[props.keyField]
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

// 找到主键对应的 index (数组模式) 或返回 null (对象模式)
function _findIndex(row) {
  if (isObjectMode.value) return -1
  const key = _rowKey(row)
  return props.rowsRef.findIndex((r) => {
    if (_isComposite.value) {
      return _keyParts.value.every((k, i) => r[k] === key[i])
    }
    return r[props.keyField] === key
  })
}

function onSave() {
  saving.value = true
  try {
    if (isObjectMode.value) {
      // 资金表 (singleton): 直接替换
      const { [props.keyField]: _, ...rest } = form.value
      // 保留 keyField (e.g. 'id'), 用 Object.assign
      Object.assign(props.rowsRef, form.value)
    } else {
      const idx = editing.value ? _findIndex(form.value) : -1
      const newRow = { ...form.value }
      if (idx >= 0) {
        // 改: 替换原行 (触发响应式)
        props.rowsRef.splice(idx, 1, newRow)
      } else {
        // 增: 插到队首
        props.rowsRef.unshift(newRow)
      }
    }
    ElMessage.success(editing.value ? '已保存' : '已新增')
    dialogVisible.value = false
  } catch (e) {
    ElMessage.error(`保存失败: ${e.message || e}`)
  } finally {
    saving.value = false
  }
}

function onDelete(row) {
  ElMessageBox.confirm(
    `确认删除 ${props.keyField} = ${JSON.stringify(_rowKey(row))} ?`,
    '删除确认',
    { type: 'warning' }
  ).then(() => {
    if (isObjectMode.value) {
      // 资金: 清空值
      Object.keys(props.rowsRef).forEach((k) => {
        props.rowsRef[k] = props.fields.find(f => f.key === k)?.type === 'number' ? 0 : ''
      })
    } else {
      const idx = _findIndex(row)
      if (idx >= 0) props.rowsRef.splice(idx, 1)
    }
    ElMessage.success('已删除')
  }).catch(() => {})  // 取消
}

function onClear() {
  ElMessageBox.confirm(
    `确认清空 ${props.title || '此表'} ? 业务页面也会立即看到空数据`,
    '清空确认',
    { type: 'warning' }
  ).then(() => {
    if (isObjectMode.value) {
      Object.keys(props.rowsRef).forEach((k) => {
        props.rowsRef[k] = props.fields.find(f => f.key === k)?.type === 'number' ? 0 : ''
      })
    } else {
      props.rowsRef.splice(0, props.rowsRef.length)
    }
    ElMessage.success('已清空')
  }).catch(() => {})
}
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
.table-with-pagination {
  display: flex;
  flex-direction: column;
}
.dtv-pagination {
  display: flex;
  justify-content: flex-end;
  padding: var(--space-3, 8px) var(--space-4, 12px);
  border-top: 1px solid var(--border-light, #ebeef5);
  flex-shrink: 0;
}
</style>
