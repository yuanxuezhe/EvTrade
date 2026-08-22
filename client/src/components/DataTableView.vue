<!--
  DataTableView.vue — 通用表格组件 (排序 + 分页 + 每页大小)

  Props:
    - columns: Array — 列定义 [{ key, label, width, minWidth, align, headerAlign, sortable, fixed, vBind, type, reserveSelection, selectable }]
                      type='selection' → 渲染勾选列 (width 默认 48, 不参与排序)
    - data: Array — 完整数据 (组件内部做排序+分页)
    - rowKey: String | Function — 行唯一标识 (默认 'id'; 勾选/高亮行依赖它)
    - loading: Boolean — 表格加载态 (内部 v-loading)
    - defaultSort: { prop, order } — 默认排序 prop + 'ascending'|'descending'
    - defaultPageSize: Number — 默认每页大小 (50)
    - pageSizes: Array — 可选每页大小 [50, 100, 200, 500]
    - height: String — el-table 高度 (默认 '100%'; 弹窗等无固定高父容器内传具体像素如 '400', 配 autoShell 用)
    - autoShell: Boolean — 容器自适应模式 (默认 false): shell/body 用纯 block 布局,
                     适合弹窗/内容撑高的父容器; 与 height 组合: autoShell + height='400' → 定高表,
                     autoShell + height='' + max-height → 内容自适应 (部分 el-table 版本 fluid 有坑, 推荐定高)
    - emptyDescription: String — 空数据提示
    - size: 'small' | 'default' — el-table 大小 (默认 'small')
    - border: Boolean — 显示纵向边框 (默认 false)
    - rowClassName: Function — 传给 el-table :row-class-name
    - cellClassName: Function — 传给 el-table :cell-class-name

  Events:
    - @sort-change — 排序变化 { prop, order }
    - @page-change — 翻页 { page, pageSize }
    - @selection-change — 勾选变化 rows (仅列定义含 type='selection' 时触发)
    - @row-click / @row-dblclick — 透传 row

  Slots:
    - 命名 slot: `column-{key}` — 自定义列内容, scope: { row, column }
    - `empty` — 自定义空状态

  暴露方法 (ref 可调, 透传到内部 el-table):
    - clearSelection / toggleRowSelection(row, selected) / toggleAllSelection / setCurrentRow / clearSort

  其他要点:
    - loading prop / selection 列 / @selection-change / ref 方法暴露
    - rowKey prop 绑定到 el-table
    - height 支持 '' 禁用固定高 (配合 max-height)
    - border/rowClassName/cellClassName/size props
    - 默认排序: 无用户排序时也做 defaultSort 排序(不依赖 el-table 内置)
    - 所有列统一 column-{key} slot
    - 列默认 sortable="custom", 可 sortable: false 关闭
    - columns 支持 vBind 属性合并 (COL.NUMBER 等常量)
-->
<template>
  <div class="dtv-shell" :class="{ 'dtv-shell-auto': autoShell || !height }">
    <div class="dtv-body">
      <el-table
        ref="tableRef"
        :data="pagedData"
        :show-overflow-tooltip="true"
        :stripe="stripe"
        :size="size"
        :border="border"
        :row-class-name="rowClassName"
        :cell-class-name="cellClassName"
        :row-key="rowKey"
        :height="height || undefined"
        v-loading="loading"
        @sort-change="onSortChange"
        @selection-change="(rows) => $emit('selection-change', rows)"
        @row-click="(row) => $emit('row-click', row)"
        @row-dblclick="(row) => $emit('row-dblclick', row)"
        class="dtv-table"
        v-bind="$attrs"
      >
        <template v-for="col in columns" :key="col.type === 'selection' ? '__selection__' : col.key">
          <el-table-column
            v-if="col.type === 'selection'"
            type="selection"
            :width="col.width || 48"
            :reserve-selection="col.reserveSelection"
            :selectable="col.selectable"
          />
          <el-table-column
            v-else
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
        </template>

        <template #empty>
          <slot name="empty">
            <el-empty :description="emptyDescription" :image-size="80" />
          </slot>
        </template>
      </el-table>
    </div>

    <!-- 分页: 数据量 > pageSize 时显示 -->
    <div v-if="!noPagination && data.length > pageSize" class="dtv-pagination">
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
  rowKey: { type: [String, Function], default: 'id' },
  loading: { type: Boolean, default: false },
  defaultSort: { type: Object, default: () => ({}) },
  defaultPageSize: { type: Number, default: 50 },
  pageSizes: { type: Array, default: () => [50, 100, 200, 500] },
  height: { type: String, default: '100%' },
  emptyDescription: { type: String, default: '暂无数据' },
  size: { type: String, default: 'small' },
  border: { type: Boolean, default: false },
  rowClassName: { type: Function, default: null },
  cellClassName: { type: Function, default: null },
  noPagination: { type: Boolean, default: false },
  stripe: { type: Boolean, default: true },
  autoShell: { type: Boolean, default: false },
})

const emit = defineEmits(['sort-change', 'page-change', 'row-click', 'row-dblclick', 'selection-change'])

// el-table 实例引用 — 供 defineExpose 把常用表格方法透传给父级 (勾选/高亮/排序)
const tableRef = ref(null)

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
  if (props.noPagination) return sortedData.value
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

// ---- 暴露 el-table 常用方法 (供父级 ref 调用) ----
function clearSelection() { tableRef.value?.clearSelection?.() }
function toggleRowSelection(row, selected) { tableRef.value?.toggleRowSelection?.(row, selected) }
function toggleAllSelection() { tableRef.value?.toggleAllSelection?.() }
function setCurrentRow(row) { tableRef.value?.setCurrentRow?.(row) }
function clearSort() { tableRef.value?.clearSort?.() }
defineExpose({ clearSelection, toggleRowSelection, toggleAllSelection, setCurrentRow, clearSort })
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

/* auto 高度模式 (height='' 时): 用在无固定高度父容器 (如弹窗) 内。
   固定模式 (height=100%) 用 flex 布局撑满, 但 flex-basis 0 会在无固定高父容器里
   把 shell/body/表体塌缩成 0 → 这里把 shell/body 还原成纯 block, 让 el-table 恢复
   原生 max-height 行为 (fluid-height), 不再依赖 flex */
.dtv-shell-auto {
  display: block;
  height: auto;
  overflow: visible;
}
.dtv-shell-auto .dtv-body {
  display: block;
  flex: none;
  overflow: visible;
}
.dtv-shell-auto .dtv-body .el-table {
  height: auto;
  display: block;
}
.dtv-shell-auto .dtv-body .el-table .el-table__body-wrapper {
  flex: none;
  overflow-y: auto;
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
