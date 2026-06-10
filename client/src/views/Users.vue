<template>
  <div class="users-view fade-in-up" v-loading="loading">
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
        <el-button type="primary" :icon="Plus" @click="openCreate">新建用户</el-button>
      </div>
    </div>

    <!-- 表格 -->
    <div class="content-card">
      <el-table
        :data="pagedUsers"
        v-loading="loading"
        style="width: 100%"
        :default-sort="{ prop: 'id', order: 'ascending' }"
        row-key="id"
      >
        <el-table-column prop="id" label="ID" width="70" sortable>
          <template #default="{ row }">
            <span class="text-mono text-secondary">#{{ row.id }}</span>
          </template>
        </el-table-column>

        <el-table-column prop="username" label="用户名" min-width="140">
          <template #default="{ row }">
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
        </el-table-column>

        <el-table-column prop="email" label="邮箱" min-width="180">
          <template #default="{ row }">
            <span v-if="row.email" class="text-secondary">{{ row.email }}</span>
            <span v-else class="text-placeholder">--</span>
          </template>
        </el-table-column>

        <el-table-column prop="role" label="角色" width="120">
          <template #default="{ row }">
            <span class="role-chip" :class="`role-${row.role}`">
              {{ ROLE_LABEL[row.role] || row.role }}
            </span>
          </template>
        </el-table-column>

        <el-table-column prop="is_active" label="状态" width="90">
          <template #default="{ row }">
            <el-tag
              :type="row.is_active ? 'success' : 'danger'"
              size="small"
              effect="light"
            >
              {{ row.is_active ? '已启用' : '已禁用' }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="last_login_at" label="最近登录" width="160">
          <template #default="{ row }">
            <span class="text-mono text-secondary">
              {{ formatDateTime(row.last_login_at) }}
            </span>
          </template>
        </el-table-column>

        <el-table-column prop="created_at" label="创建时间" width="160">
          <template #default="{ row }">
            <span class="text-mono text-secondary">
              {{ formatDateTime(row.created_at) }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="240" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button size="small" link type="primary" @click="openEdit(row)">
                编辑
              </el-button>
              <el-button
                size="small"
                link
                type="warning"
                @click="openResetPwd(row)"
              >
                重置密码
              </el-button>
              <el-button
                size="small"
                link
                :type="row.is_active ? 'info' : 'success'"
                :disabled="row.id === authStore.user?.id"
                @click="toggleActive(row)"
              >
                {{ row.is_active ? '禁用' : '启用' }}
              </el-button>
              <el-button
                size="small"
                link
                type="danger"
                :disabled="row.id === authStore.user?.id"
                @click="confirmDelete(row)"
              >
                删除
              </el-button>
            </div>
          </template>
        </el-table-column>

        <template #empty>
          <el-empty description="暂无用户" :image-size="100" />
        </template>
      </el-table>

      <div class="pagination">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="filteredUsers.length"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next, jumper"
        />
      </div>
    </div>

    <!-- 新建/编辑 用户弹窗 -->
    <el-dialog
      v-model="editVisible"
      :title="editForm.id ? '编辑用户' : '新建用户'"
      width="480px"
      :close-on-click-modal="false"
      align-center
    >
      <el-form
        ref="editFormRef"
        :model="editForm"
        :rules="editRules"
        label-position="top"
        size="default"
      >
        <el-form-item label="用户名" prop="username">
          <el-input
            v-model="editForm.username"
            placeholder="3-32位字母/数字/_/-/."
            :disabled="!!editForm.id"
          />
        </el-form-item>

        <el-form-item
          v-if="!editForm.id"
          label="初始密码"
          prop="password"
        >
          <el-input
            v-model="editForm.password"
            type="password"
            show-password
            placeholder="至少 6 位"
          />
        </el-form-item>

        <el-form-item label="角色" prop="role">
          <el-radio-group v-model="editForm.role">
            <el-radio-button value="admin">管理员</el-radio-button>
            <el-radio-button value="trader">交易员</el-radio-button>
            <el-radio-button value="viewer">只读用户</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="姓名" prop="full_name">
          <el-input v-model="editForm.full_name" placeholder="可选" />
        </el-form-item>

        <el-form-item label="邮箱" prop="email">
          <el-input v-model="editForm.email" placeholder="可选" />
        </el-form-item>

        <el-form-item v-if="!editForm.id" label="启用状态" prop="is_active">
          <el-switch
            v-model="editForm.is_active"
            active-text="启用"
            inactive-text="禁用"
            inline-prompt
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="editLoading" @click="submitEdit">
          {{ editForm.id ? '保存' : '创建' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 重置密码弹窗 -->
    <el-dialog
      v-model="pwdVisible"
      title="重置密码"
      width="420px"
      :close-on-click-modal="false"
      align-center
    >
      <el-form
        ref="pwdFormRef"
        :model="pwdForm"
        :rules="pwdRules"
        label-position="top"
        size="default"
      >
        <el-form-item label="目标用户">
          <div class="target-user">
            <div class="avatar small" :class="`role-${pwdTarget?.role}`">
              {{ (pwdTarget?.full_name || pwdTarget?.username || '').charAt(0).toUpperCase() }}
            </div>
            <div>
              <div class="user-name">{{ pwdTarget?.username }}</div>
              <div class="text-secondary" style="font-size: 12px">
                {{ pwdTarget?.full_name || ROLE_LABEL[pwdTarget?.role] }}
              </div>
            </div>
          </div>
        </el-form-item>
        <el-form-item label="新密码" prop="new_password">
          <el-input
            v-model="pwdForm.new_password"
            type="password"
            show-password
            placeholder="至少 6 位"
          />
        </el-form-item>
        <el-form-item label="确认新密码" prop="confirm">
          <el-input
            v-model="pwdForm.confirm"
            type="password"
            show-password
            placeholder="再次输入新密码"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdVisible = false">取消</el-button>
        <el-button type="primary" :loading="pwdLoading" @click="submitResetPwd">
          确认重置
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Refresh, Plus } from '@element-plus/icons-vue'
import { userApi } from '../api'
import { useAuthStore } from '../stores/auth'
import { formatDateTime } from '../utils/format'

const authStore = useAuthStore()

const ROLE_LABEL = { admin: '管理员', trader: '交易员', viewer: '只读用户' }

const users = ref([])
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)

const filters = reactive({ keyword: '', role: '' })

const countByRole = computed(() => {
  const map = { admin: 0, trader: 0, viewer: 0 }
  for (const u of users.value) if (map[u.role] !== undefined) map[u.role]++
  return map
})

const disabledCount = computed(() => users.value.filter((u) => !u.is_active).length)

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

const pagedUsers = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredUsers.value.slice(start, start + pageSize.value)
})

async function refresh() {
  loading.value = true
  try {
    users.value = await userApi.list({
      keyword: filters.keyword || undefined,
      role: filters.role || undefined
    })
    page.value = 1
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '加载失败')
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  filters.keyword = ''
  filters.role = ''
  refresh()
}

// ============================================================
// 新建 / 编辑
// ============================================================
const editVisible = ref(false)
const editLoading = ref(false)
const editFormRef = ref(null)
const editForm = reactive({
  id: null,
  username: '',
  password: '',
  role: 'trader',
  email: '',
  full_name: '',
  is_active: true
})

const editRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    {
      validator: (_r, v, cb) =>
        /^[A-Za-z0-9_\-.]{3,32}$/.test(v) ? cb() : cb(new Error('3-32位字母/数字/_/-/.')),
      trigger: 'blur'
    }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码长度至少 6 位', trigger: 'blur' }
  ],
  role: [{ required: true, message: '请选择角色', trigger: 'change' }],
  email: [
    {
      validator: (_r, v, cb) =>
        !v || /^[\w.+-]+@[\w-]+\.[\w.-]+$/.test(v) ? cb() : cb(new Error('邮箱格式不正确')),
      trigger: 'blur'
    }
  ]
}

function openCreate() {
  Object.assign(editForm, {
    id: null,
    username: '',
    password: '',
    role: 'trader',
    email: '',
    full_name: '',
    is_active: true
  })
  editVisible.value = true
  setTimeout(() => editFormRef.value?.clearValidate(), 50)
}

function openEdit(row) {
  Object.assign(editForm, {
    id: row.id,
    username: row.username,
    password: '',
    role: row.role,
    email: row.email || '',
    full_name: row.full_name || '',
    is_active: row.is_active
  })
  editVisible.value = true
  setTimeout(() => editFormRef.value?.clearValidate(), 50)
}

async function submitEdit() {
  if (!editFormRef.value) return
  const valid = await editFormRef.value.validate().catch(() => false)
  if (!valid) return

  editLoading.value = true
  try {
    if (editForm.id) {
      await userApi.update(editForm.id, {
        role: editForm.role,
        email: editForm.email,
        full_name: editForm.full_name,
        is_active: editForm.is_active
      })
      ElMessage.success('已保存')
    } else {
      await userApi.create({
        username: editForm.username.trim(),
        password: editForm.password,
        role: editForm.role,
        email: editForm.email,
        full_name: editForm.full_name,
        is_active: editForm.is_active
      })
      ElMessage.success('用户已创建')
    }
    editVisible.value = false
    refresh()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  } finally {
    editLoading.value = false
  }
}

// ============================================================
// 重置密码
// ============================================================
const pwdVisible = ref(false)
const pwdLoading = ref(false)
const pwdFormRef = ref(null)
const pwdTarget = ref(null)
const pwdForm = reactive({ new_password: '', confirm: '' })

const pwdRules = {
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '密码长度至少 6 位', trigger: 'blur' }
  ],
  confirm: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_r, v, cb) =>
        v === pwdForm.new_password ? cb() : cb(new Error('两次输入不一致')),
      trigger: 'blur'
    }
  ]
}

function openResetPwd(row) {
  pwdTarget.value = row
  pwdForm.new_password = ''
  pwdForm.confirm = ''
  pwdVisible.value = true
  setTimeout(() => pwdFormRef.value?.clearValidate(), 50)
}

async function submitResetPwd() {
  if (!pwdFormRef.value) return
  const valid = await pwdFormRef.value.validate().catch(() => false)
  if (!valid) return
  pwdLoading.value = true
  try {
    await userApi.resetPassword(pwdTarget.value.id, pwdForm.new_password)
    ElMessage.success(`已重置 ${pwdTarget.value.username} 的密码`)
    pwdVisible.value = false
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '重置失败')
  } finally {
    pwdLoading.value = false
  }
}

// ============================================================
// 启用 / 禁用
// ============================================================
async function toggleActive(row) {
  const next = !row.is_active
  const action = next ? '启用' : '禁用'
  try {
    await ElMessageBox.confirm(
      `确定要${action}用户「${row.username}」吗？`,
      `${action}确认`,
      { type: 'warning', confirmButtonText: action, cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    await userApi.update(row.id, { is_active: next })
    ElMessage.success(`已${action}`)
    refresh()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || `${action}失败`)
  }
}

// ============================================================
// 删除
// ============================================================
async function confirmDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确定要删除用户「${row.username}」吗？该操作不可撤销。`,
      '删除确认',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger'
      }
    )
  } catch {
    return
  }
  try {
    await userApi.delete(row.id)
    ElMessage.success('已删除')
    refresh()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '删除失败')
  }
}

onMounted(refresh)
</script>

<style scoped>
.users-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
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

.target-user {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  background: var(--bg-soft);
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-base);
}

.pagination {
  padding: var(--space-3) var(--space-4);
  display: flex;
  justify-content: flex-end;
  border-top: 1px solid var(--border-light);
}

@media (max-width: 1100px) {
  .stats-row { grid-template-columns: repeat(2, 1fr); }
}
</style>
