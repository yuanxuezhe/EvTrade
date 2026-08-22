<template>
  <div class="oplog" :class="{ expanded: !collapsed }">
    <div class="oplog-header" @click="toggle" :title="collapsed ? '点击展开' : '点击收缩'">
      <div class="oplog-title">
        <el-icon class="title-icon" :class="{ pulse: unread > 0 }"><Document /></el-icon>
        <!-- 折叠态：不显示"操作记录"字样；展开态才显示 -->
        <span v-if="!collapsed" class="title-text">操作记录</span>
        <el-badge
          v-if="unread > 0"
          :value="unread"
          :max="99"
          class="title-badge"
        />
        <!-- 折叠态：在标题行显示最新 1 条摘要 -->
        <span v-if="collapsed && latestEntry" class="latest-line text-secondary">
          {{ formatTime(latestEntry.ts) }} {{ tagLabel(latestEntry.tag) }} · {{ latestEntry.message }}
        </span>
      </div>
      <div class="oplog-actions" @click.stop>
        <el-tag
          v-for="(st, key) in refCounts"
          :key="key"
          size="small"
          :type="statusTagType(st)"
          effect="plain"
          class="ref-tag"
        >
          {{ refLabel(key) }} {{ statusLabel(st) }}
        </el-tag>
        <el-tooltip content="清空记录" placement="top">
          <button class="icon-btn-sm" @click="onClear">
            <el-icon><Delete /></el-icon>
          </button>
        </el-tooltip>
        <el-tooltip :content="collapsed ? '展开' : '收缩'" placement="top">
          <button class="icon-btn-sm toggle-btn" @click="toggle">
            <el-icon :class="{ 'is-collapsed': collapsed }">
              <component :is="collapsed ? ArrowUp : ArrowDown" />
            </el-icon>
          </button>
        </el-tooltip>
      </div>
    </div>

    <div class="oplog-body" v-show="!collapsed">
      <!-- 标签筛选条 -->
      <div class="oplog-filter">
        <span class="filter-label">筛选：</span>
        <el-check-tag
          v-for="t in availableTags"
          :key="t"
          :checked="!activeTags[t]"
          @change="toggleTagFilter(t)"
          class="filter-tag"
          :class="`tag-${t}`"
        >
          {{ tagLabel(t) }} <span class="tag-count">({{ tagCount(t) }})</span>
        </el-check-tag>
        <span v-if="filteredCount !== entries.length" class="filter-summary text-secondary">
          · 显示 {{ filteredCount }} / {{ entries.length }}
        </span>
      </div>

      <div v-if="displayEntries.length === 0" class="oplog-empty">
        <el-icon><InfoFilled /></el-icon>
        <span>当前筛选下暂无记录</span>
      </div>
      <el-scrollbar v-else max-height="220px">
        <ul class="oplog-list">
          <li
            v-for="e in displayEntries"
            :key="e.id"
            class="oplog-item"
            :class="`lvl-${e.level}`"
          >
            <span class="dot"></span>
            <span class="time text-mono">{{ formatTime(e.ts) }}</span>
            <el-tag
              :type="tagTagType(e.tag)"
              size="small"
              effect="plain"
              class="tag-chip"
            >
              {{ tagLabel(e.tag) }}
            </el-tag>
            <el-tag
              :type="sourceTagType(e.source)"
              size="small"
              effect="plain"
              class="src-tag"
            >
              {{ sourceLabel(e.source) }}
            </el-tag>
            <span class="msg">{{ e.message }}</span>
            <span v-if="e.detail" class="detail text-secondary">{{ e.detail }}</span>
          </li>
        </ul>
      </el-scrollbar>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Document, Delete, ArrowUp, ArrowDown, InfoFilled
} from '@element-plus/icons-vue'
import { useHoldingsStore } from '../stores/holdings'

const props = defineProps({
  // 折叠状态外部控制（v-model:expanded）
  expanded: { type: Boolean, default: undefined }
})
const emit = defineEmits(['update:expanded', 'refresh'])

// 默认折叠（贴下边框单行）
const collapsed = ref(true)

const holdingsStore = useHoldingsStore()
const entries = computed(() => holdingsStore.loadHistory || [])
const refCounts = computed(() => holdingsStore.refCounts || {})

// 最新一条（折叠态显示在标题行）
const latestEntry = computed(() => entries.value[0] || null)

// 未读数 = 总数 - 折叠后用户未查看的（仅 ok/err/warn 算提醒）
const _seen = ref(0)
const unread = computed(() => {
  if (!collapsed.value) {
    _seen.value = entries.value.length
    return 0
  }
  return Math.max(0, entries.value.length - _seen.value)
})

// === 标签筛选 =============================================================
const ALL_TAGS = ['缓存', '交易', '用户', '系统']
// activeTags[tag] = true 表示该标签被过滤掉（不显示）
const activeTags = ref({})
ALL_TAGS.forEach((t) => (activeTags.value[t] = false))

// 实际有记录的标签
const availableTags = computed(() => {
  const set = new Set(entries.value.map((e) => e.tag).filter(Boolean))
  return ALL_TAGS.filter((t) => set.has(t))
})

function tagCount(t) {
  return entries.value.filter((e) => e.tag === t).length
}

function tagLabel(t) {
  return ({ 缓存: '缓存', 交易: '交易', 用户: '用户', 系统: '系统' })[t] || t
}
function tagTagType(t) {
  // el-tag type: success/warning/info/danger/primary
  return ({ 缓存: 'warning', 交易: 'success', 用户: 'primary', 系统: 'info' })[t] || 'info'
}
function toggleTagFilter(t) {
  activeTags.value[t] = !activeTags.value[t]
}

const filteredEntries = computed(() =>
  entries.value.filter((e) => !activeTags.value[e.tag])
)
const filteredCount = computed(() => filteredEntries.value.length)

// 显示条数：最多 100
const displayEntries = computed(() => filteredEntries.value.slice(0, 100))

// 外部 v-model:expanded 双向绑定
watch(() => props.expanded, (v) => {
  if (typeof v === 'boolean') collapsed.value = !v
})

function formatTime(ts) {
  const d = new Date(ts)
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function levelLabel(l) {
  return { ok: '成功', info: '信息', warn: '警告', err: '失败' }[l] || l
}
function sourceLabel(s) {
  return { bootstrap: '启动', refresh: '刷新', user: '用户', ws: 'WS', rpc: 'RPC' }[s] || s
}
function sourceTagType(s) {
  return { bootstrap: 'info', refresh: 'info', user: 'primary', ws: 'success', rpc: 'warning' }[s] || 'info'
}
function refLabel(k) {
  return { asset: '资金', positions: '持仓', orders: '委托', trades: '成交' }[k] || k
}
function statusLabel(s) {
  return { idle: '未加载', loading: '加载中', ok: '✓', fail: '✗' }[s] || s
}
function statusTagType(s) {
  return { idle: 'info', loading: 'warning', ok: 'success', fail: 'danger' }[s] || 'info'
}

async function onClear() {
  try {
    await ElMessageBox.confirm('清空所有操作记录？', '确认', {
      type: 'warning',
      confirmButtonText: '清空',
      cancelButtonText: '取消'
    })
    holdingsStore.clearHistory()
    _seen.value = 0
    ElMessage.success('已清空')
  } catch { /* cancelled */ }
}

function toggle() {
  collapsed.value = !collapsed.value
  emit('update:expanded', !collapsed.value)
}

defineExpose({ toggle, collapsed })
</script>

<style scoped>
/* === 贴底固定条 === */
.oplog {
  position: fixed;
  left: var(--sidebar-w, 220px);
  right: 0;
  bottom: 0;
  z-index: 90;
  /* 改走 var(--bg-elevated), 暗色模式下不再死白 (与卡片/对话框/表格同源变量) */
  background: var(--bg-elevated);
  border-top: 1px solid var(--border-base);
  box-shadow: 0 -2px 12px rgba(0, 0, 0, 0.08);
  transition: box-shadow var(--transition-base);
  /* 折叠态默认高度 44px；展开态 max-height:280px */
  max-height: 44px;
  overflow: hidden;
}
.oplog.expanded {
  max-height: 320px;
}
.app-layout.collapsed .oplog {
  left: var(--sidebar-collapsed-w, 64px);
}
/* 移动端：抽屉式侧栏时 left:0，宽度更小 */
.app-layout.is-mobile .oplog {
  left: 0;
  max-height: 44px;
}
.app-layout.is-mobile .oplog.expanded {
  max-height: 60vh;
}

/* 折叠态：单行 44px 紧贴下边框 */
.oplog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 44px;
  padding: 0 var(--space-4);
  cursor: pointer;
  user-select: none;
  transition: background var(--transition-fast);
}
.oplog-header:hover {
  background: var(--bg-soft);
}
.oplog-header:active {
  background: var(--bg-muted, rgba(0, 0, 0, 0.04));
}

.oplog-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-weight: 600;
  font-size: 13px;
  color: var(--text-primary);
  flex: 1;
  min-width: 0;
  overflow: hidden;
}
.title-icon {
  color: var(--brand-primary);
  flex-shrink: 0;
  transition: transform var(--transition-base);
}
.title-icon.pulse {
  animation: pulse 1.6s ease-in-out infinite;
}
.title-text { letter-spacing: 0.5px; flex-shrink: 0; }
.title-badge { margin-left: 2px; flex-shrink: 0; }
.latest-line {
  font-size: 11px;
  font-weight: 400;
  margin-left: var(--space-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}

.oplog-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}

.ref-tag {
  font-size: 10px;
  font-family: var(--font-mono);
  height: 20px;
  line-height: 20px;
  padding: 0 6px;
}

.icon-btn-sm {
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  background: transparent;
  border: 1px solid var(--border-base);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
  font-size: 12px;
}
.icon-btn-sm:hover {
  color: var(--brand-primary);
  border-color: var(--brand-primary);
  background: var(--bg-soft);
}
.icon-btn-sm.toggle-btn .is-collapsed {
  transform: rotate(180deg);
  transition: transform var(--transition-base);
}
.icon-btn-sm.spinning :deep(.el-icon) {
  animation: spin 1s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }
@keyframes pulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.15); }
}

/* === 展开区域 === */
.oplog-body {
  border-top: 1px solid var(--border-light);
  padding: var(--space-2) var(--space-4) var(--space-3);
  /* 同上, 跟随主题 */
  background: var(--bg-elevated);
  animation: slideDown 0.18s ease-out;
}
@keyframes slideDown {
  from { opacity: 0; transform: translateY(-4px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* 标签筛选条 */
.oplog-filter {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  padding: 6px 0;
  border-bottom: 1px dashed var(--border-light);
  margin-bottom: 6px;
  font-size: 12px;
}
.filter-label {
  color: var(--text-secondary);
  margin-right: 2px;
  font-size: 12px;
}
.filter-tag {
  cursor: pointer;
  font-size: 12px;
}
.tag-count {
  font-size: 10px;
  color: var(--text-secondary);
  margin-left: 2px;
}
.filter-summary {
  font-size: 11px;
  font-family: var(--font-mono);
}

.oplog-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: var(--space-4) 0;
  color: var(--text-secondary);
  font-size: 12px;
}

.oplog-list {
  list-style: none;
  margin: 0;
  padding: var(--space-2) 0 0;
  font-family: var(--font-mono);
  font-size: 12px;
}

.oplog-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 5px 0;
  border-bottom: 1px dashed var(--border-light);
}
.oplog-item:last-child { border-bottom: 0; }

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-secondary);
  flex-shrink: 0;
}
.lvl-ok .dot { background: var(--color-up); }
.lvl-warn .dot { background: #ffa726; }
.lvl-err .dot { background: var(--color-down); }
.lvl-info .dot { background: var(--brand-primary); }

.time {
  color: var(--text-secondary);
  font-size: 11px;
  width: 70px;
  flex-shrink: 0;
}

.tag-chip, .src-tag {
  font-size: 10px;
  height: 18px;
  line-height: 18px;
  padding: 0 6px;
  flex-shrink: 0;
}

.msg {
  color: var(--text-primary);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font-sans);
  font-size: 12px;
}

.detail {
  font-size: 10px;
  color: var(--text-secondary);
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font-sans);
}
</style>
