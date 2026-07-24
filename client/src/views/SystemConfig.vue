<template>
  <div class="system-config fade-in-up">
    <el-card class="config-card" shadow="hover">
      <template #header>
        <div class="card-header">
          <span class="card-title">⚙️ 系统配置 (v78 统一表)</span>
          <div class="header-actions">
            <el-tag size="small" type="info">当前用户: {{ currentUser }}</el-tag>
            <el-button :icon="Refresh" size="small" @click="loadAll">刷新</el-button>
            <el-button type="primary" :icon="Plus" size="small" @click="openCreate">新增配置</el-button>
          </div>
        </div>
      </template>

      <el-table
        :data="rows"
        v-loading="loading"
        border
        stripe
        :row-class-name="rowClass"
        empty-text="暂无配置"
      >
        <el-table-column prop="user" label="用户" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.user === '0' ? 'success' : 'warning'">
              {{ row.user === '0' ? '默认' : row.user }}
            </el-tag>
            <el-tooltip v-if="row.has_override" content="该配置存在用户专属覆盖" placement="top">
              <el-icon style="margin-left:4px;color:#e6a23c"><Warning /></el-icon>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column prop="cfg_key" label="Key" width="180" />
        <el-table-column prop="cfg_val" label="值" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="!row._editing" class="mono">{{ row.cfg_val }}</span>
            <el-input v-else v-model="row._draft.cfg_val" size="small" />
          </template>
        </el-table-column>
        <el-table-column prop="desc" label="说明" width="280">
          <template #default="{ row }">
            <span v-if="!row._editing">{{ row.desc || '—' }}</span>
            <el-input v-else v-model="row._draft.desc" size="small" placeholder="可选说明" />
          </template>
        </el-table-column>
        <el-table-column prop="inherited" label="继承" width="70" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.inherited" size="small" type="info" effect="plain">继承</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" align="right">
          <template #default="{ row }">
            <template v-if="!row._editing">
              <el-button
                v-if="canEdit(row)"
                size="small" :icon="Edit" link type="primary"
                @click="startEdit(row)"
              >编辑</el-button>
              <el-button
                v-if="canDelete(row)"
                size="small" :icon="Delete" link type="danger"
                @click="onDelete(row)"
              >删除</el-button>
            </template>
            <template v-else>
              <el-button size="small" type="primary" @click="commitEdit(row)">保存</el-button>
              <el-button size="small" @click="cancelEdit(row)">取消</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新增/编辑 dialog -->
    <el-dialog v-model="dlg.visible" :title="dlg.title" width="500px" @closed="dlgReset">
      <el-form :model="dlg.form" label-width="100px">
        <el-form-item label="用户">
          <el-radio-group v-model="dlg.form.user">
            <el-radio value="0">默认 (全局)</el-radio>
            <el-radio :value="currentUser">我的 (专属)</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="Key">
          <el-input v-model="dlg.form.cfg_key" :disabled="dlg.editing" placeholder="如: commission_rate" maxlength="64" />
        </el-form-item>
        <el-form-item label="值">
          <el-input v-model="dlg.form.cfg_val" placeholder="配置值 (string)" maxlength="512" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="dlg.form.desc" placeholder="可选" maxlength="255" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="dlg.saving" @click="dlgSubmit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Plus, Edit, Delete, Warning } from '@element-plus/icons-vue'
import { sysconfigApi } from '../api/sysconfig'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const currentUser = computed(() => auth.user?.username || 'trader')
const isAdmin = computed(() => auth.user?.role === 'admin')

const loading = ref(false)
const rows = ref([])

const dlg = reactive({ visible: false, editing: false, saving: false, title: '', form: { user: '0', cfg_key: '', cfg_val: '', desc: '' } })

async function loadAll() {
  loading.value = true
  try {
    const data = await sysconfigApi.list()
    rows.value = data.map(r => ({ ...r, _editing: false, _draft: {} }))
  } catch (e) {
    ElMessage.error('加载配置失败: ' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

function rowClass({ row }) {
  return row.inherited ? 'inherited-row' : ''
}

function canEdit(row) {
  // user='0' 仅 admin 可编辑; user=自己 任何用户可编辑
  if (row.user === '0') return isAdmin.value
  return row.user === currentUser.value || isAdmin.value
}

function canDelete(row) {
  if (row.inherited) return false  // 继承的不能直接删
  return canEdit(row)
}

function startEdit(row) {
  row._editing = true
  row._draft = { cfg_val: row.cfg_val, desc: row.desc }
}

function cancelEdit(row) {
  row._editing = false
  row._draft = {}
}

async function commitEdit(row) {
  // 优先走 PUT (row 已存在); 不存在走 POST
  try {
    const target = row.user
    if (target === '0' && !isAdmin.value) {
      ElMessage.warning('只有 admin 可改默认配置')
      return
    }
    await sysconfigApi.upsert({
      user: target,
      cfg_key: row.cfg_key,
      cfg_val: row._draft.cfg_val,
      desc: row._draft.desc || row.desc,
    })
    row.cfg_val = row._draft.cfg_val
    row.desc = row._draft.desc || row.desc
    row._editing = false
    ElMessage.success('已保存')
  } catch (e) {
    ElMessage.error('保存失败: ' + (e?.message || e))
  }
}

async function onDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确认删除 [${row.user}/${row.cfg_key}]?`,
      '删除配置',
      { type: 'warning' }
    )
    await sysconfigApi.remove(row.cfg_key, row.user)
    ElMessage.success('已删除')
    await loadAll()
  } catch (e) {
    if (e !== 'cancel' && e?.message !== 'cancel') {
      ElMessage.error('删除失败: ' + (e?.message || e))
    }
  }
}

function openCreate() {
  dlg.editing = false
  dlg.title = '新增配置'
  dlg.form = { user: isAdmin.value ? '0' : currentUser.value, cfg_key: '', cfg_val: '', desc: '' }
  dlg.visible = true
}

function dlgReset() {
  dlg.form = { user: '0', cfg_key: '', cfg_val: '', desc: '' }
  dlg.editing = false
  dlg.saving = false
}

async function dlgSubmit() {
  if (!dlg.form.cfg_key || !dlg.form.cfg_val) {
    ElMessage.warning('Key 和 Val 不能为空')
    return
  }
  if (dlg.form.user === '0' && !isAdmin.value) {
    ElMessage.warning('只有 admin 可写默认配置')
    return
  }
  dlg.saving = true
  try {
    await sysconfigApi.upsert(dlg.form)
    ElMessage.success('已新增')
    dlg.visible = false
    await loadAll()
  } catch (e) {
    ElMessage.error('新增失败: ' + (e?.message || e))
  } finally {
    dlg.saving = false
  }
}

onMounted(loadAll)
</script>

<style scoped>
.system-config { padding: 16px; }
.config-card { margin-bottom: 16px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.card-title { font-weight: 600; }
.header-actions { display: flex; gap: 8px; align-items: center; }
.hint { color: #909399; font-size: 12px; margin-left: 8px; }
.mono { font-family: ui-monospace, monospace; }
:deep(.inherited-row) { background: #fafafa !important; opacity: 0.7; }
</style>