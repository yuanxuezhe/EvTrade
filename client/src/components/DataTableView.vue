<!--
  DataTableView.vue — 通用表格组件 (排序 + 分页 + 每页大小)

  Props:
    - columns: Array — 列定义 [{ key, label, width, minWidth, align, headerAlign, sortable, fixed, vBind }]
    - data: Array — 完整数据 (组件内部做排序+分页)
    - rowKey: String — 行唯一标识字段 (默认 'id')
    - defaultSort: { prop, order } — 默认排序 prop + 'ascending'|'descending'
    - defaultPageSize: Number — 默认每页大小 (20)
    - pageSizes: Array — 可选每页大小 [10, 20, 50, 100]
    - height: String — el-table 高度 (默认 '100%')
    - emptyDescription: String — 空数据提示
    - size: 'small' | 'default' — el-table 大小 (默认 'small')
    - border: Boolean — 显示纵向边框 (默认 false)
    - rowClassName: Function — 传给 el-table :row-class-name
    - cellClassName: Function — 传给 el-table :cell-class-name

  Events:
    - @sort-change — 排序变化 { prop, order }
    - @page-change — 翻页 { page, pageSize }
    - @row-click / @row-dblclick — 透传 row

  Slots:
    - 命名 slot: `column-{key}` — 自定义列内容, scope: { row, column }
    - `empty` — 自定义空状态

  v2 改进:
    - 新增 border/rowClassName/cellClassName/size props
    - 默认排序: 无用户排序时也做 defaultSort 排序(不依赖 el-table 内置)
    - slot 简化: 所有列统一 column-{key} slot
    - 列默认 sortable="custom", 可 sortable: false 关闭
    - columns 支持 vBind 属性合并 (COL.NUMBER 等常量)
-->
<template>
  <div class="dtv-shell">
    <div class="dtv-body">
      <el-table
        :data="pagedData"
        :show-overflow-tooltip="true"
        :stripe="true"
        :size="size"
        :border="border"
        :row-class-name="rowClassName"
        :cell-class-name="cellClassName"
        :height="height"
        @sort-change="onSortChange"
        @row-click="(row) => $emit('row-click', row)"
        @row-dblclick="(row) => $emit('row-dblclick', row)"
        class="dtv-table"
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
          :sortable="col.sortable === false ? false : 'custom'"
          :fixed="col.fixed"
          v-bind="col.vBind || {}"
        >
          <template #default="{ row }">
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
        @current-change="$emit('page-change', { page: page, pageSize: pageSize })"
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
  size: { type: String, default: 'small' },
  border: { type: Boolean, default: false },
  rowClassName: { type: Function, default: null },
  cellClassName: { type: Function, default: null },
})

const emit = defineEmits(['sort-change', 'page-change', 'row-click', 'row-dblclick'])

const page = ref(1)
const pageSize = ref(props.defaultPageSize)
const sortProp = ref('')
const sortOrder = ref('')

/**
 * 排序比较函数
 */
function sortCompare(va, vb, dir) {
  if (va == null && vb == null) return 0
  if (va == null) return dir
  if (vb == null) return -dir
  if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * dir
  return String(va).localeCompare(String(vb)) * dir
}

/**
 * 客户端排序
 * - 有用户排序 → 用用户排序
 * - 无用户排序但有 defaultSort → 用 defaultSort
 * - 否则原样返回
 */
const sortedData = computed(() => {
  const prop = sortProp.value || props.defaultSort?.prop
  const order = sortProp.value ? (sortOrder.value || 'descending') : props.defaultSort?.order
  if (!prop || !order) return props.data
  const dir = order === 'ascending' ? 1 : -1
  return [...props.data].sort((a, b) => sortCompare(a[prop], b[prop], dir))
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
