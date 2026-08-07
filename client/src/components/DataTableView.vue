<!--
  DataTableView.vue — 通用表格组件 (排序 + 分页 + 每页大小)

  Props:
    - columns: Array — 列定义 [{ key, label, width, minWidth, align, sortable, fixed, slotName }]
    - data: Array — 完整数据 (组件内部做排序+分页)
    - row-key: String — 行唯一标识字段 (默认 'id')
    - default-sort: { prop, order } — 默认排序 prop + 'ascending'|'descending'
    - default-page-size: Number — 默认每页大小 (20)
    - page-sizes: Array — 可选每页大小 [10, 20, 50, 100]
    - height: String — el-table 高度 (默认 '100%')
    - empty-description: String — 空数据提示

  Events:
    - @sort-change — 排序变化 { prop, order }
    - @page-change — 翻页 { page, pageSize }
    - @row-click / @row-dblclick — 透传 row

  Slots:
    - 命名 slot: `column-{key}` — 自定义列内容, scope: { row, column }
    - `empty` — 自定义空状态
-->
<template>
  <div class="dtv-shell">
    <div class="dtv-body">
      <el-table
        :data="pagedData"
        :show-overflow-tooltip="true"
        :height="height"
        stripe
        size="small"
        class="dtv-table"
        :default-sort="defaultSort"
        @sort-change="onSortChange"
        @row-click="$emit('row-click', $event[0])"
        @row-dblclick="$emit('row-dblclick', $event[0])"
        v-bind="$attrs"
      >
        <el-table-column
          v-for="col in columns"
          :key="col.key"
          :prop="col.key"
          :label="col.label"
          :width="col.width"
          :min-width="col.minWidth"
          :align="col.align || 'left'"
          :header-align="col.headerAlign || 'left'"
          :sortable="col.sortable !== false"
          :fixed="col.fixed"
          :show-overflow-tooltip="col.tooltip !== false"
        >
          <template v-if="col.slotName" #[col.slotName]="scope">
            <slot :name="`column-${col.key}`" :row="scope.row" :column="col">
              {{ scope.row[col.key] }}
            </slot>
          </template>
          <template v-else #default="{ row }">
            <slot :name="`column-${col.key}`" :row="row" :column="col">
              {{ row[col.key] }}
            </slot>
          </template>
        </el-table-column>

        <template #empty>
          <slot name="empty">
            <el-empty :description="emptyDescription" :image-size="80" />
          </slot>
        </template>
      </el-table>
    </div>

    <!-- 分页: 数据量 > pageSize 时显示 -->
    <div v-if="data.length > pageSize" class="dtv-pagination">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="data.length"
        :page-sizes="pageSizes"
        layout="total, sizes, prev, pager, next"
        size="small"
        background
        @current-change="$emit('page-change', { page, pageSize })"
      />
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  columns: { type: Array, required: true },
  data: { type: Array, required: true },
  rowKey: { type: String, default: 'id' },
  defaultSort: { type: Object, default: () => ({}) },
  defaultPageSize: { type: Number, default: 20 },
  pageSizes: { type: Array, default: () => [10, 20, 50, 100] },
  height: { type: String, default: '100%' },
  emptyDescription: { type: String, default: '暂无数据' },
})

const emit = defineEmits(['sort-change', 'page-change', 'row-click', 'row-dblclick'])

const page = ref(1)
const pageSize = ref(props.defaultPageSize)
const sortProp = ref(props.defaultSort?.prop || '')
const sortOrder = ref(props.defaultSort?.order || '')

// 客户端排序
const sortedData = computed(() => {
  if (!sortProp.value || !sortOrder.value) return props.data
  const prop = sortProp.value
  const order = sortOrder.value === 'descending' ? -1 : 1
  return [...props.data].sort((a, b) => {
    const va = a[prop]
    const vb = b[prop]
    if (va == null && vb == null) return 0
    if (va == null) return 1
    if (vb == null) return -1
    if (typeof va === 'string' && typeof vb === 'string') {
      return va.localeCompare(vb) * order
    }
    return ((va > vb) - (va < vb)) * order
  })
})

// 分页
const pagedData = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return sortedData.value.slice(start, start + pageSize.value)
})

function onSortChange({ prop, order }) {
  sortProp.value = prop || ''
  sortOrder.value = order || ''
  page.value = 1
  emit('sort-change', { prop: sortProp.value, order: sortOrder.value })
}

// 数据变化时重置到第 1 页
watch(() => props.data.length, () => {
  page.value = 1
})
</script>

<style scoped>
.dtv-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.dtv-body {
  flex: 1 1 0;
  min-height: 0;
  overflow: hidden;
  padding: 0 var(--space-3, 8px);
}

:deep(.dtv-body .el-table) {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
}
:deep(.dtv-body .el-table .el-table__body-wrapper) {
  flex: 1 1 0;
  min-height: 0;
  overflow-y: auto;
}

.dtv-table {
  width: 100%;
}

.dtv-pagination {
  display: flex;
  justify-content: flex-end;
  padding: var(--space-3, 8px) var(--space-4, 12px);
  border-top: 1px solid var(--border-light, #ebeef5);
  flex-shrink: 0;
}
</style>
