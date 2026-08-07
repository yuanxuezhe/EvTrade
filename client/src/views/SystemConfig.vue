<template>
  <div class="system-config fade-in-up" :style="rootStyle">
    <!-- 工具栏 -->
    <div class="content-card filter-bar">
      <div class="filter-left">
        <span class="card-title">系统配置</span>
        <el-tag size="small" type="info">当前用户: {{ currentUser }}</el-tag>
      </div>
      <div class="filter-right">
        <el-button :icon="Refresh" :loading="loading" size="small" @click="loadAll">刷新</el-button>
        <el-button type="primary" :icon="Plus" size="small" @click="openCreate">新增配置</el-button>
      </div>
    </div>

    <!-- 表格 -->
    <div class="content-card table-wrap" v-loading="loading">
      <DataTableView
        :columns="configColumns"
        :data="rows"
        :empty-description="'暂无配置'"
        :row-class-name="rowClass"
        :no-pagination="true"
        size="default"
      >
        <template #column-user="{ row }">
          <el-tag size="small" :type="row.user === '0' ? 'success' : 'warning'">
            {{ row.user === '0' ? '默认' : row.user }}
          </el-tag>
          <el-tooltip v-if="row.has_override" content="该配置存在用户专属覆盖" placement="top">
            <el-icon class="override-icon"><Warning /></el-icon>
          </el-tooltip>
        </template>

        <template #column-cfg_key="{ row }">
          <span class="text-mono">{{ row.cfg_key }}</span>
        </template>

        <template #column-cfg_val="{ row }">
          <span v-if="!row._editing" class="text-mono">{{ row.cfg_val }}</span>
          <el-input v-else v-model="row._draft.cfg_val" size="small" />
        </template>

        <template #column-desc="{ row }">
          <span v-if="!row._editing">{{ row.desc || '—' }}</span>
          <el-input v-else v-model="row._draft.desc" size="small" placeholder="可选说明" />
        </template>

        <template #column-inherited="{ row }">
          <el-tag v-if="row.inherited" size="small" type="info" effect="plain">继承</el-tag>
        </template>

        <template #column-action="{ row }">
          <template v-if="!row._editing">
            <el-button
              v-if="canEdit(row)"
              size="small" link type="primary"
              @click.stop="startEdit(row)"
            >编辑</el-button>
            <el-button
              v-if="canDelete(row)"
              size="small" link type="danger"
              @click.stop="onDelete(row)"
            >删除</el-button>
          </template>
          <template v-else>
            <el-button size="small" type="primary" @click.stop="commitEdit(row)">保存</el-button>
            <el-button size="small" @click.stop="cancelEdit(row)">取消</el-button>
          </template>
        </template>
      </DataTableView>
    </div>

    <!-- 新增 dialog -->
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
import { Refresh, Plus, Warning } from '@element-plus/icons-vue'
import DataTableView from '../components/DataTableView.vue'
import { COL } from '../utils/tableColumns'
import { sysconfigApi } from '../api/sysconfig'
import { useAuthStore } from '../stores/auth'
import { useUiStore } from '../stores/ui'

const auth = useAuthStore()
const uiStore = useUiStore()
const currentUser = computed(() => auth.user?.username || 'trader')
const isAdmin = computed(() => auth.user?.role === 'admin')
const rootStyle = computed(() => ({ '--oplog-extra': uiStore.oplogExpanded ? '260px' : '0px' }))

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
  if (row.user === '0') return isAdmin.value
  return row.user === currentUser.value || isAdmin.value
}

function canDelete(row) {
  if (row.inherited) return false
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
  const target = row.user
  if (target === '0' && !isAdmin.value) {
    ElMessage.warning('只有 admin 可改默认配置')
    return
  }
  try {
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

// 列定义
const configColumns = [
  { key: 'user', label: '用户', width: 130, sortable: false },
  { key: 'cfg_key', label: 'Key', width: 200 },
  { key: 'cfg_val', label: '值', minWidth: 150, sortable: false },
  { key: 'desc', label: '说明', width: 300, sortable: false },
  { key: 'inherited', label: '继承', width: 80, align: 'center', headerAlign: 'center', sortable: false },
  { key: 'action', label: '操作', width: 160, fixed: 'right', align: 'center', sortable: false },
]

onMounted(loadAll)
</script>

<style scoped>
.system-config { display: flex; flex-direction: column; gap: var(--space-4); height: calc(100% - var(--oplog-extra, 0px)); min-height: 0; overflow: hidden; }
.filter-bar { display: flex; justify-content: space-between; align-items: center; padding: var(--space-3) var(--space-4); flex-wrap: wrap; gap: var(--space-3); }
.filter-left { display: flex; gap: var(--space-2); align-items: center; }
.filter-right { display: flex; gap: var(--space-2); align-items: center; }
.card-title { font-weight: 600; }
.table-wrap { flex: 1 1 0; min-height: 0; display: flex; flex-direction: column; }
.text-mono { font-family: var(--font-mono, 'JetBrains Mono', 'Consolas', monospace); }
.override-icon { margin-left: 4px; color: #e6a23c; }
:deep(.inherited-row) { background: #fafafa !important; opacity: 0.7; }
</style>
