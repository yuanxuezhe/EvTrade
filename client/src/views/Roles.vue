<!--
  Roles.vue — 角色管理页 (rbac-roles-module 2026-09-21)

  三段布局:
  ┌─────────────────┬────────────────────────────────┐
  │ 角色列表         │ 选中角色详情 + page_keys 多选    │
  │ (含新建/删除)    │ (按业务分组: 交易/查询/系统/策略) │
  └─────────────────┴────────────────────────────────┘

  行为:
  - 进入页面 → list() 拉全部角色
  - 选中某 role → 右侧 detail + permission 多选加载
  - 新建/编辑/删除 → 调 api + 重新 list
  - 内置 role (is_builtin=1) 不可删/不可改 name; super_admin 不能去掉 '*' 通配
  - 修改 page_keys → PUT /roles/{id}/permissions (整体覆盖)
-->
<template>
  <div class="roles-page">
    <!-- 顶部 toolbar -->
    <div class="page-header">
      <h2>角色管理</h2>
      <div class="header-actions">
        <el-button type="primary" :icon="Plus" @click="onCreate">新建角色</el-button>
        <el-button :icon="Refresh" @click="loadAll">刷新</el-button>
      </div>
    </div>

    <div class="page-body">
      <!-- 左侧: 角色列表 -->
      <div class="roles-list">
        <el-table
          :data="roles"
          highlight-current-row
          stripe
          height="100%"
          @current-change="onSelectRole"
          v-loading="loading"
        >
          <el-table-column prop="name" label="name" min-width="120">
            <template #default="{ row }">
              <span class="text-mono">{{ row.name }}</span>
              <el-tag v-if="row.is_builtin" type="warning" size="small" effect="plain" style="margin-left: 6px">内置</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="display_name" label="显示名" min-width="120" />
          <el-table-column label="page_keys" min-width="80" align="center">
            <template #default="{ row }">
              <el-tag size="small">{{ row.page_keys.length }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 右侧: 角色详情 + page_keys 多选 -->
      <div class="role-detail">
        <template v-if="!current">
          <el-empty description="选择左侧角色查看详情" />
        </template>
        <template v-else>
          <div class="detail-header">
            <h3>
              {{ current.display_name }}
              <el-tag v-if="current.is_builtin" type="warning" size="small" effect="plain">内置</el-tag>
            </h3>
            <div class="detail-actions">
              <el-button type="danger" size="small" :icon="Delete" :disabled="current.is_builtin" @click="onDelete">删除</el-button>
            </div>
          </div>

          <el-form label-width="100px" class="detail-form">
            <el-form-item label="name">
              <span class="text-mono">{{ current.name }}</span>
              <span class="hint">（不可改）</span>
            </el-form-item>
            <el-form-item label="显示名">
              <el-input v-model="editForm.display_name" :disabled="current.is_builtin" placeholder="中文显示名" />
            </el-form-item>
            <el-form-item label="描述">
              <el-input v-model="editForm.description" type="textarea" :rows="2" :disabled="current.is_builtin" placeholder="角色用途说明" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" size="small" @click="onSaveInfo">保存</el-button>
            </el-form-item>
          </el-form>

          <el-divider content-position="left">页面权限</el-divider>

          <!-- rbac-roles-module (2026-09-22): 用 el-tree 树状展示, 跟左侧导航同源 (PAGE_NAV_TREE) -->
          <div class="perm-tree-wrap">
            <div class="perm-tree-actions">
              <el-button link size="small" @click="expandAllPermTree(true)">展开全部</el-button>
              <el-button link size="small" @click="expandAllPermTree(false)">折叠全部</el-button>
              <el-button link size="small" @click="selectAllPermTree">全选</el-button>
              <el-button link size="small" @click="clearAllPermTree">清空</el-button>
              <span class="perm-count">
                已选 <b>{{ editForm.page_keys.length }}</b> / {{ totalPageKeys }} 项
              </span>
            </div>
            <el-tree
              ref="permTreeRef"
              :data="treeData"
              node-key="key"
              :default-checked-keys="editForm.page_keys"
              :default-expanded-keys="groupKeys"
              show-checkbox
              check-strictly
              class="perm-tree"
              @check="onPermTreeCheck"
            >
              <template #default="{ data }">
                <span class="perm-tree-node">
                  <span class="perm-tree-label">{{ data.label }}</span>
                  <span v-if="data.pageKey" class="perm-tree-key">{{ data.pageKey }}</span>
                </span>
              </template>
            </el-tree>
          </div>

          <div class="perm-actions">
            <el-button type="primary" @click="onSavePermissions">保存权限</el-button>
            <el-button @click="resetPermissions">重置</el-button>
          </div>
        </template>
      </div>
    </div>

    <!-- 新建角色 dialog -->
    <el-dialog v-model="createVisible" title="新建角色" width="500px" :close-on-click-modal="false">
      <el-form ref="createFormRef" :model="createForm" :rules="createRules" label-width="100px">
        <el-form-item label="name" prop="name">
          <el-input v-model="createForm.name" placeholder="英文唯一 key (a-z 0-9 _ -)" />
        </el-form-item>
        <el-form-item label="显示名" prop="display_name">
          <el-input v-model="createForm.display_name" placeholder="中文显示名" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="createForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="初始权限">
          <!-- rbac-roles-module (2026-09-22): 用 el-tree 跟左侧导航同源 -->
          <el-tree
            ref="createPermTreeRef"
            :data="treeData"
            node-key="key"
            show-checkbox
            check-strictly
            :default-checked-keys="createForm.page_keys"
            :default-expanded-keys="groupKeys"
            class="perm-tree perm-tree-create"
            @check="onCreatePermTreeCheck"
          >
            <template #default="{ data }">
              <span class="perm-tree-node">
                <span class="perm-tree-label">{{ data.label }}</span>
                <span v-if="data.pageKey" class="perm-tree-key">{{ data.pageKey }}</span>
              </span>
            </template>
          </el-tree>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="onCreateSubmit" :loading="creating">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Delete } from '@element-plus/icons-vue'
import { rolesApi } from '../api/roles'
import { PAGE_NAV_TREE, asElTreeData } from '../utils/pageNavTree'

// ── 树状结构 (PAGE_NAV_TREE 与左侧导航同源) ─────────────────────────────────
// 用于: 右侧"页面权限"多选 / 新建 dialog 的"初始权限"多选
const treeData = ref(asElTreeData(PAGE_NAV_TREE))
const totalPageKeys = computed(() => PAGE_NAV_TREE.reduce((sum, g) => sum + (g.children?.length || 0), 0))
const groupKeys = computed(() => PAGE_NAV_TREE.map((g) => g.key))

// ── state ──────────────────────────────────────────────────────────────────
const roles = ref([])
const loading = ref(false)
const current = ref(null)  // 选中角色全量 (含 page_keys)

const editForm = reactive({
  display_name: '',
  description: '',
  page_keys: [],
})

const createVisible = ref(false)
const creating = ref(false)
const createFormRef = ref(null)
const createForm = reactive({
  name: '',
  display_name: '',
  description: '',
  page_keys: [],
})

// rbac-roles-module: el-tree ref (用于"展开/折叠/全选"操作)
const permTreeRef = ref(null)
const createPermTreeRef = ref(null)

const createRules = {
  name: [{ required: true, message: '请输入 name', trigger: 'blur' }],
  display_name: [{ required: true, message: '请输入显示名', trigger: 'blur' }],
}

// ── fetch ──────────────────────────────────────────────────────────────────
async function loadAll() {
  loading.value = true
  try {
    // http 拦截器自动从 {code:0, list:[...]} 解包成 list 数组
    const r = await rolesApi.list()
    roles.value = Array.isArray(r) ? r : (r?.list || [])
  } catch (e) {
    // http 拦截器已 toast, 这里不再二次提示避免噪音
    console.warn('[roles] loadAll failed:', e?.msg || e?.detail?.msg || e?.message)
  } finally {
    loading.value = false
  }
}

function onSelectRole(row) {
  if (!row) return
  current.value = row
  editForm.display_name = row.display_name || ''
  editForm.description = row.description || ''
  editForm.page_keys = [...(row.page_keys || [])]
}

function resetPermissions() {
  if (!current.value) return
  editForm.page_keys = [...(current.value.page_keys || [])]
}

// rbac-roles-module (2026-09-22): 树状结构 helpers
// el-tree 的 check 事件回调: 把 checkedKeys (含 group key + page_key) → 过滤掉 group key 只留 page_key
function _checkedKeysToPageKeys(checkedKeys) {
  const groupKeys = new Set(treeData.value.map((g) => g.key))
  return checkedKeys.filter((k) => !groupKeys.has(k))
}

function onPermTreeCheck(_checkedNode, { checkedKeys }) {
  editForm.page_keys = _checkedKeysToPageKeys(checkedKeys)
}

function onCreatePermTreeCheck(_checkedNode, { checkedKeys }) {
  createForm.page_keys = _checkedKeysToPageKeys(checkedKeys)
}

function expandAllPermTree(expand) {
  // el-tree 节点 .expanded 赋值 (note: 不能 a?.b?.c = d, babel parser 不支持)
  if (!permTreeRef.value?.store?.nodesMap) return
  const nodesMap = permTreeRef.value.store.nodesMap
  for (const g of treeData.value) {
    const node = nodesMap[g.key]
    if (node) node.expanded = expand
  }
}

function selectAllPermTree() {
  const allKeys = treeData.value.flatMap((g) => g.children.map((p) => p.key))
  editForm.page_keys = [...allKeys]
}

function clearAllPermTree() {
  editForm.page_keys = []
}

async function onSaveInfo() {
  if (!current.value) return
  try {
    const updated = await rolesApi.update(current.value.id, {
      display_name: editForm.display_name,
      description: editForm.description,
    })
    ElMessage.success('已保存')
    // 局部更新 + 重新 list 保证 is_builtin 锁生效
    Object.assign(current.value, updated)
    await loadAll()
  } catch (e) {
    ElMessage.error('保存失败: ' + (e?.msg || e?.message || '未知'))
  }
}

async function onSavePermissions() {
  if (!current.value) return
  try {
    await rolesApi.setPermissions(current.value.id, editForm.page_keys)
    ElMessage.success('权限已保存')
    await loadAll()
    // 重新选中
    const r = roles.value.find((x) => x.id === current.value.id)
    if (r) onSelectRole(r)
  } catch (e) {
    ElMessage.error('保存失败: ' + (e?.msg || e?.message || '未知'))
  }
}

async function onDelete() {
  if (!current.value) return
  await ElMessageBox.confirm(
    `确认删除角色 "${current.value.display_name}" (${current.value.name})？\n该角色的所有用户绑定 + 权限将一并移除 (CASCADE).`,
    '删除角色',
    { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
  )
  try {
    await rolesApi.remove(current.value.id)
    ElMessage.success('已删除')
    current.value = null
    await loadAll()
  } catch (e) {
    ElMessage.error('删除失败: ' + (e?.msg || e?.message || '未知'))
  }
}

function onCreate() {
  createForm.name = ''
  createForm.display_name = ''
  createForm.description = ''
  createForm.page_keys = []
  createVisible.value = true
}

async function onCreateSubmit() {
  if (!createFormRef.value) return
  try {
    await createFormRef.value.validate()
  } catch {
    return
  }
  creating.value = true
  try {
    await rolesApi.create({
      name: createForm.name.trim(),
      display_name: createForm.display_name.trim(),
      description: createForm.description || null,
      page_keys: createForm.page_keys,
    })
    ElMessage.success('已创建')
    createVisible.value = false
    await loadAll()
  } catch (e) {
    ElMessage.error('创建失败: ' + (e?.msg || e?.message || '未知'))
  } finally {
    creating.value = false
  }
}

// ── watch: 切换 role 时同步 editForm (Vue 3 reactivity 已自动同步, 但保留显式确保) ──
watch(() => current.value?.id, () => { /* onSelectRole 已显式赋值 */ })

onMounted(loadAll)
</script>

<style scoped>
.roles-page {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 90px);
  padding: 16px;
  box-sizing: border-box;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.page-header h2 {
  margin: 0;
  font-size: 20px;
}
.page-body {
  display: flex;
  flex: 1;
  min-height: 0;
  gap: 16px;
}
.roles-list {
  width: 360px;
  flex-shrink: 0;
  background: #fff;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  overflow: hidden;
}
.role-detail {
  flex: 1;
  min-width: 0;
  background: #fff;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  padding: 20px;
  overflow-y: auto;
}
.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.detail-header h3 {
  margin: 0;
  font-size: 16px;
}
.detail-form {
  margin-bottom: 8px;
}
.perm-tree-wrap {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  background: var(--el-fill-color-blank);
}
.perm-tree-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: var(--el-fill-color-light);
}
.perm-count {
  margin-left: auto;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.perm-tree {
  padding: 8px 12px;
  max-height: 480px;
  overflow-y: auto;
}
.perm-tree-create {
  max-height: 280px;
}
.perm-tree-node {
  display: inline-flex;
  align-items: baseline;
  gap: 8px;
}
.perm-tree-key {
  font-family: var(--font-mono, Consolas, monospace);
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.perm-actions {
  margin-top: 20px;
  display: flex;
  gap: 8px;
}
.hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-left: 8px;
}
.text-mono {
  font-family: var(--font-mono, Consolas, monospace);
}
</style>