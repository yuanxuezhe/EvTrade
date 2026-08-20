<template>
  <div class="users-view fade-in-up" :style="rootStyle">
    <!-- 顶部概览 -->
    <section class="stats-row">
      <div class="stat-pill">
        <div class="pill-label">总用户数</div>
        <div class="pill-value text-mono">{{ users.length }}</div>
      </div>
      <div class="stat-pill">
        <div class="pill-label">管理员</div>
        <div class="pill-value text-mono text-up">{{ countByRole.admin }}</div>
      </div>
      <div class="stat-pill">
        <div class="pill-label">交易员</div>
        <div class="pill-value text-mono text-info">{{ countByRole.trader }}</div>
      </div>
      <div class="stat-pill">
        <div class="pill-label">只读用户</div>
        <div class="pill-value text-mono">{{ countByRole.viewer }}</div>
      </div>
      <div class="stat-pill">
        <div class="pill-label">已禁用</div>
        <div class="pill-value text-mono text-down">{{ disabledCount }}</div>
      </div>
    </section>

    <!-- 筛选 + 操作 -->
    <div class="content-card filter-bar">
      <div class="filter-left">
        <el-input
          v-model="filters.keyword"
          placeholder="搜索用户名 / 邮箱 / 姓名"
          clearable
          :prefix-icon="Search"
          style="width: 240px"
          @keyup.enter="refresh"
        />
        <el-select v-model="filters.role" placeholder="角色" clearable style="width: 120px">
          <el-option label="管理员" value="admin" />
          <el-option label="交易员" value="trader" />
          <el-option label="只读用户" value="viewer" />
        </el-select>
        <el-button @click="resetFilters">清空</el-button>
      </div>
      <div class="filter-right">
        <el-button :icon="Refresh" @click="refresh" :loading="loading">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="actions.openCreate()">新建用户</el-button>
      </div>
    </div>

    <!-- 表格 -->
    <div class="content-card table-wrap" v-loading="loading">
      <DataTableView
        :columns="userColumns"
        :data="filteredUsers"
        :default-sort="{ prop: 'id', order: 'ascending' }"
        :default-page-size="20"
        :page-sizes="[10, 20, 50]"
        empty-description="暂无用户"
      >
        <template #column-username="{ row }">
          <div class="user-cell">
            <div class="avatar" :class="`role-${row.role}`">
              {{ (row.full_name || row.username).charAt(0).toUpperCase() }}
            </div>
            <div class="user-meta">
              <div class="user-name">{{ row.username }}</div>
              <div v-if="row.full_name" class="user-fullname">{{ row.full_name }}</div>
            </div>
          </div>
        </template>
        <template #column-email="{ row }">
          <span v-if="row.email" class="text-secondary">{{ row.email }}</span>
          <span v-else class="text-placeholder">--</span>
        </template>
        <template #column-role="{ row }">
          <span class="role-chip" :class="`role-${row.role}`">
            {{ ROLE_LABEL[row.role] || row.role }}
          </span>
        </template>
        <template #column-is_active="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'danger'" size="small" effect="light">
            {{ row.is_active ? '已启用' : '已禁用' }}
          </el-tag>
        </template>
        <template #column-last_login_at="{ row }">
          <span class="text-mono text-secondary">{{ formatDateTime(row.last_login_at) }}</span>
        </template>
        <template #column-created_at="{ row }">
          <span class="text-mono text-secondary">{{ formatDateTime(row.created_at) }}</span>
        </template>
        <template #column-action="{ row }">
          <div class="row-actions">
            <el-button size="small" link type="primary" @click="actions.openEdit(row)">编辑</el-button>
            <el-button size="small" link type="warning" @click="actions.openResetPwd(row)">重置密码</el-button>
            <el-button
              size="small" link
              :type="row.is_active ? 'info' : 'success'"
              :disabled="row.id === (authStore.user && authStore.user.id)"
              @click="onToggleActive(row)"
            >{{ row.is_active ? '禁用' : '启用' }}</el-button>
            <el-button
              size="small" link type="danger"
              :disabled="row.id === (authStore.user && authStore.user.id)"
              @click="onConfirmDelete(row)"
            >删除</el-button>
          </div>
        </template>
      </DataTableView>
    </div>

    <!-- 弹窗：phase-2 拆分到子组件 -->
    <UserEditDialog
      ref="editDialogEl"
      v-model:visible="actions.editVisible.value"
      :loading="actions.editLoading.value"
      :form="actions.editForm"
      :rules="actions.editRules"
      @submit="onSubmitEdit"
    />

    <UserResetPwdDialog
      ref="pwdDialogEl"
      v-model:visible="actions.pwdVisible.value"
      :loading="actions.pwdLoading.value"
      :form="actions.pwdForm"
      :rules="actions.pwdRules"
      :target="actions.pwdTarget.value"
      @submit="onSubmitResetPwd"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, Refresh, Plus } from '@element-plus/icons-vue'
import { userApi } from '../api'
import { useAuthStore } from '../stores/auth'
import { formatDateTime } from '../utils/format'
import { COL } from '../utils/tableColumns'
import DataTableView from '../components/DataTableView.vue'
import { useUiStore } from '../stores/ui'
import { useUserActions } from '../composables/useUserActions'
import UserEditDialog from '../components/users/UserEditDialog.vue'
import UserResetPwdDialog from '../components/users/UserResetPwdDialog.vue'

const authStore = useAuthStore()
const uiStore = useUiStore()
const rootStyle = computed(() => ({ '--oplog-extra': uiStore.oplogExpanded ? '260px' : '0px' }))

const ROLE_LABEL = { admin: '管理员', trader: '交易员', viewer: '只读用户' }

const users = ref([])
const loading = ref(false)

const filters = reactive({ keyword: '', role: '' })

const countByRole = computed(() => {
  const map = { admin: 0, trader: 0, viewer: 0 }
  for (const u of users.value) if (map[u.role] !== undefined) map[u.role]++
  return map
})

const disabledCount = computed(() => users.value.filter((u) => !u.is_active).length)

const userColumns = [
  { key: 'id', label: 'ID', width: 90 },
  { key: 'username', label: '用户名', vBind: COL.STRING },
  { key: 'email', label: '邮箱', vBind: COL.STRING },
  { key: 'role', label: '角色', width: 100 },
  { key: 'is_active', label: '状态', width: 100 },
  { key: 'last_login_at', label: '最近登录', vBind: COL.TIME },
  { key: 'created_at', label: '创建时间', vBind: COL.TIME },
  { key: 'action', label: '操作', width: 250, fixed: 'right', sortable: false },
]

const filteredUsers = computed(() => {
  const kw = filters.keyword.trim().toLowerCase()
  return users.value.filter((u) => {
    if (filters.role && u.role !== filters.role) return false
    if (kw) {
      const blob = [u.username, u.email, u.full_name]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
      if (!blob.includes(kw)) return false
    }
    return true
  })
})

async function refresh() {
  loading.value = true
  try {
    users.value = await userApi.list({
      keyword: filters.keyword || undefined,
      role: filters.role || undefined
    })
  } catch (e) {
    ElMessage.error((e.response && e.response.data && e.response.data.detail) || '加载失败')
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  filters.keyword = ''
  filters.role = ''
  refresh()
}

// ===== Actions (弹窗状态 + 业务方法) =====
const actions = useUserActions()

// 把 dialog 组件 instance 注入到 actions.dialogRefs, 让 submit 调 validate
// (不能 actions.editDialogRef = ref, 因为那只覆盖 actions 上的属性, 没改 useUserActions
// 闭包内的引用 → submit 时 dialogRef.value 永远是 null → 静默退出)
// 改用 reactive 容器 actions.dialogRefs.edit = ref, submitEdit 读 dialogRefs.edit.value
const editDialogEl = ref(null)
const pwdDialogEl = ref(null)
actions.dialogRefs.edit = editDialogEl
actions.dialogRefs.pwd = pwdDialogEl

async function onSubmitEdit() {
  const ok = await actions.submitEdit()
  if (ok) refresh()
}

async function onSubmitResetPwd() {
  // 重置密码不刷新列表（用户没变，仅 msg 提示）
  await actions.submitResetPwd()
}

async function onToggleActive(row) {
  const ok = await actions.toggleActive(row)
  if (ok) refresh()
}

async function onConfirmDelete(row) {
  const ok = await actions.confirmDelete(row)
  if (ok) refresh()
}

onMounted(refresh)
</script>

<style scoped>
.users-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  height: calc(100% - var(--oplog-extra, 0px));
  min-height: 0;
  overflow: hidden;
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: var(--space-3);
}

.stat-pill {
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
  display: flex;
  align-items: center;
  justify-content: space-between;
  transition: all var(--transition-fast);
}

.stat-pill:hover {
  border-color: var(--brand-primary);
}

.pill-label {
  font-size: 12px;
  color: var(--text-secondary);
}

.pill-value {
  font-size: 18px;
  font-weight: 700;
}

.text-up { color: var(--color-up); }
.text-down { color: var(--color-down); }
.text-info { color: var(--color-info); }

.filter-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-3) var(--space-4);
  flex-wrap: wrap;
  gap: var(--space-3);
}

.filter-left {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.filter-right {
  display: flex;
  gap: var(--space-2);
}

.user-cell {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-weight: 700;
  color: white;
  font-size: 14px;
  flex-shrink: 0;
}

.avatar.small {
  width: 30px;
  height: 30px;
  font-size: 12px;
}

.avatar.role-admin { background: var(--brand-gradient); }
.avatar.role-trader { background: var(--color-up-gradient); }
.avatar.role-viewer { background: linear-gradient(135deg, #5fa8ff, #82b9ff); }

.user-meta {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}

.user-name {
  font-weight: 600;
  color: var(--text-primary);
  font-size: 13px;
}

.user-fullname {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 2px;
}

.role-chip {
  display: inline-flex;
  align-items: center;
  padding: 2px 10px;
  border-radius: var(--radius-xs);
  font-size: 12px;
  font-weight: 600;
  color: white;
}

.role-chip.role-admin { background: var(--brand-gradient); }
.role-chip.role-trader { background: var(--color-up-gradient); }
.role-chip.role-viewer { background: linear-gradient(135deg, #5fa8ff, #82b9ff); }

.row-actions {
  display: flex;
  gap: var(--space-1);
  flex-wrap: wrap;
}

.table-wrap {
  flex: 1 1 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

@media (max-width: 1100px) {
  .stats-row { grid-template-columns: repeat(2, 1fr); }
}
</style>
