<!--
  ScriptDev.vue — 策略开发页 (script-strategy change)

  布局: 左侧脚本列表 + 顶部新建按钮
        右侧: 顶部名称/描述/状态 → 大代码编辑器 (textarea 高亮) → 参数 schema 表格
        底部: 保存 / 测试回测 / 删除 按钮

  代码编辑器: 不引入 Monaco (项目无 dep), 用 textarea + 等宽字体 + 行号侧栏 (轻量实现)
-->
<template>
  <div class="script-dev-view fade-in-up" data-el="script-dev-view">
    <header class="sd-header">
      <h3 class="sd-title">策略开发</h3>
      <div class="sd-actions">
        <el-button :icon="Plus" type="primary" @click="onCreate" data-el="sd-create">
          新建脚本
        </el-button>
        <el-button :icon="Refresh" @click="loadScripts" data-el="sd-refresh">
          刷新
        </el-button>
      </div>
    </header>

    <div v-loading="loading" class="sd-body">
      <!-- 左侧: 脚本列表 -->
      <aside class="sd-pane sd-pane-left">
        <h4 class="sd-section-title">脚本列表</h4>
        <!-- v90+: 公开/我的筛选 -->
        <div class="sd-filter">
          <el-radio-group v-model="filterMode" size="small" @change="loadScripts">
            <el-radio-button value="all" data-el="sd-filter-all">全部</el-radio-button>
            <el-radio-button value="mine" data-el="sd-filter-mine">我的</el-radio-button>
            <el-radio-button value="public" data-el="sd-filter-public">公开市场</el-radio-button>
          </el-radio-group>
        </div>
        <div v-if="scripts.length === 0" class="sd-empty">暂无脚本</div>
        <ul v-else class="sd-script-list">
          <li
            v-for="s in scripts"
            :key="`${s.user_id}-${s.id}`"
            :class="{ active: selectedId === s.id && selectedUserId === s.user_id }"
            @click="onSelect(s)"
            data-el="sd-script-item"
          >
            <div class="sd-script-name">
              {{ s.name }}
              <el-tag v-if="s.is_public" size="small" type="success" effect="dark" style="margin-left: 4px">
                🌍 公开
              </el-tag>
              <el-tag v-else size="small" type="info" effect="plain" style="margin-left: 4px">
                🔒 私有
              </el-tag>
            </div>
            <div class="sd-script-meta">
              <el-tag size="small" :type="s.status === 'active' ? 'success' : 'info'">
                {{ s.status }}
              </el-tag>
              <span class="sd-script-params">{{ s.params_schema?.length || 0 }} 个参数</span>
              <span class="sd-script-owner" v-if="s.user_id !== currentUserId">u/{{ s.user_id }}</span>
            </div>
          </li>
        </ul>
      </aside>

      <!-- 右侧: 编辑器 -->
      <section v-if="draft || currentScript" class="sd-pane sd-pane-right">
        <!-- 顶部表单 -->
        <div class="sd-form">
          <el-form :inline="true" label-width="80px">
            <el-form-item label="脚本名">
              <el-input v-model="form.name" placeholder="如: ma_cross_v1" style="width: 220px" data-el="sd-name" />
            </el-form-item>
            <el-form-item label="状态">
              <el-select v-model="form.status" style="width: 120px">
                <el-option label="active" value="active" />
                <el-option label="paused" value="paused" />
              </el-select>
            </el-form-item>
            <el-form-item label="描述">
              <el-input v-model="form.description" placeholder="(可选)" style="width: 300px" />
            </el-form-item>
          </el-form>
        </div>

        <!-- 代码编辑器 -->
        <div class="sd-editor-wrap">
          <div class="sd-editor-label">
            <span>脚本源码</span>
            <span class="sd-editor-hint">
              实现 on_init / on_bar / on_tick / on_finish 回调, 可调 MA/EMA/RSI/doorder 等
            </span>
          </div>
          <div class="sd-editor">
            <div class="sd-line-numbers">
              <div v-for="n in lineCount" :key="n" class="sd-line-no">{{ n }}</div>
            </div>
            <textarea
              ref="editorRef"
              v-model="form.code"
              class="sd-textarea"
              spellcheck="false"
              data-el="sd-code"
              @scroll="syncScroll"
            />
          </div>
        </div>

        <!-- 参数 schema -->
        <div class="sd-params">
          <div class="sd-params-head">
            <span>参数 schema ({{ form.params_schema.length }})</span>
            <el-button :icon="Plus" size="small" plain @click="addParam" data-el="sd-add-param">
              新增参数
            </el-button>
          </div>
          <el-table :data="form.params_schema" size="small" border>
            <el-table-column label="key" width="100">
              <template #default="{ row }">
                <el-input v-model="row.key" size="small" placeholder="key" />
              </template>
            </el-table-column>
            <el-table-column label="类型" width="100">
              <template #default="{ row }">
                <el-select v-model="row.type" size="small">
                  <el-option label="int" value="int" />
                  <el-option label="float" value="float" />
                  <el-option label="choice" value="choice" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="min" width="90">
              <template #default="{ row }">
                <el-input-number v-if="row.type !== 'choice'" v-model="row.min" size="small" :step="row.type === 'int' ? 1 : 0.1" />
              </template>
            </el-table-column>
            <el-table-column label="max" width="90">
              <template #default="{ row }">
                <el-input-number v-if="row.type !== 'choice'" v-model="row.max" size="small" :step="row.type === 'int' ? 1 : 0.1" />
              </template>
            </el-table-column>
            <el-table-column label="step" width="80">
              <template #default="{ row }">
                <el-input-number v-if="row.type !== 'choice'" v-model="row.step" size="small" :step="0.1" :min="0.001" />
              </template>
            </el-table-column>
            <el-table-column label="default" width="90">
              <template #default="{ row }">
                <el-input-number v-if="row.type !== 'choice'" v-model="row.default" size="small" />
                <span v-else class="sd-hint">values[]</span>
              </template>
            </el-table-column>
            <el-table-column label="values" width="160">
              <template #default="{ row }">
                <el-input
                  v-if="row.type === 'choice'"
                  v-model="row.valuesStr"
                  size="small"
                  placeholder="逗号分隔, e.g. 1.5,2.0,3.0"
                  @change="onValuesStrChange(row)"
                />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="60" align="center">
              <template #default="{ $index }">
                <el-button :icon="Delete" size="small" link type="danger" @click="form.params_schema.splice($index, 1)" />
              </template>
            </el-table-column>
          </el-table>
        </div>

        <!-- 底部按钮 -->
        <div class="sd-footer">
          <el-button @click="onCancel" data-el="sd-cancel">取消</el-button>
          <el-button :icon="Delete" v-if="form.id" type="danger" plain @click="onDelete" data-el="sd-delete">删除</el-button>
          <el-button :icon="Document" type="primary" :loading="saving" @click="onSave" data-el="sd-save">
            保存
          </el-button>
          <el-button :icon="VideoPlay" type="success" :loading="testing" @click="onTestBacktest" data-el="sd-test">
            去测试回测
          </el-button>
        </div>
      </section>

      <section v-else class="sd-pane sd-pane-right sd-pane-empty">
        <el-empty description="选择一个脚本开始编辑，或点击右上'新建脚本'" />
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Delete, Document, VideoPlay } from '@element-plus/icons-vue'
import { scriptStrategyApi } from '../api/script_strategy'

const router = useRouter()

// ─────────────── state ───────────────
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const scripts = ref([])
const selectedId = ref(null)
const selectedUserId = ref(null)  // v90+: 复合 PK (user_id, id)
const currentScript = ref(null)
const draft = ref(null)  // 新建未保存
const filterMode = ref('all')     // v90+: 'all' / 'mine' / 'public'
const currentUserId = ref(null)   // 从 user store 拿当前用户 ID

const form = ref(_blankForm())
const editorRef = ref(null)

const lineCount = computed(() => Math.max(20, (form.value.code || '').split('\n').length))

function _blankForm() {
  return {
    id: null,
    name: '',
    description: '',
    status: 'active',
    code: '',
    params_schema: [],
  }
}

// ─────────────── load ───────────────
async function loadScripts() {
  loading.value = true
  try {
    // v90+: filterMode 决定 only_mine 参数
    const only_mine = filterMode.value === 'mine' ? 'true' : undefined
    scripts.value = await scriptStrategyApi.listScripts(only_mine)
    // 记录当前用户 ID (用于显示 owner tag)
    try {
      const u = JSON.parse(localStorage.getItem('user') || '{}')
      currentUserId.value = u.id || null
    } catch (e) {
      currentUserId.value = null
    }
  } catch (e) {
    // 错误已由 axios 拦截器弹出
  } finally {
    loading.value = false
  }
}

async function onSelect(s) {
  selectedId.value = s.id
  selectedUserId.value = s.user_id  // v90+: 复合 PK
  currentScript.value = s
  draft.value = null
  // 拷贝到 form
  form.value = {
    id: s.id,
    name: s.name,
    description: s.description,
    status: s.status,
    code: s.code,
    params_schema: (s.params_schema || []).map(p => ({
      ...p,
      valuesStr: Array.isArray(p.values) ? p.values.join(',') : '',
    })),
  }
}

async function onCreate() {
  // 拉默认模板
  try {
    const tpl = await scriptStrategyApi.getDefaultTemplate()
    form.value = {
      id: null,
      name: '',
      description: '',
      status: 'active',
      code: tpl.code,
      params_schema: (tpl.params_schema || []).map(p => ({
        ...p,
        valuesStr: Array.isArray(p.values) ? p.values.join(',') : '',
      })),
    }
    selectedId.value = null
    currentScript.value = null
    draft.value = { name: 'new' }
  } catch (e) {
    // 拦截器已弹
  }
}

function onCancel() {
  if (currentScript.value) {
    onSelect(currentScript.value)
  } else {
    form.value = _blankForm()
    draft.value = null
  }
}

async function onSave() {
  if (!form.value.name) {
    ElMessage.warning('请填写脚本名')
    return
  }
  saving.value = true
  try {
    const payload = _formToPayload(form.value)
    let saved
    if (form.value.id) {
      saved = await scriptStrategyApi.updateScript(form.value.id, payload)
      ElMessage.success('已保存')
    } else {
      saved = await scriptStrategyApi.createScript(payload)
      ElMessage.success('已创建')
    }
    await loadScripts()
    onSelect(saved)
  } catch (e) {
    // 拦截器已弹
  } finally {
    saving.value = false
  }
}

async function onDelete() {
  if (!form.value.id) return
  try {
    await ElMessageBox.confirm(`确认删除脚本 "${form.value.name}" 及其所有任务?`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await scriptStrategyApi.deleteScript(form.value.id)
    ElMessage.success('已删除')
    form.value = _blankForm()
    selectedId.value = null
    currentScript.value = null
    draft.value = null
    await loadScripts()
  } catch (e) {
    // ignored
  }
}

function onTestBacktest() {
  // 跳到 ScriptTask 页面并自动选择该脚本
  if (form.value.id) {
    router.push({ path: '/script-task', query: { script_id: form.value.id } })
  } else {
    ElMessage.warning('请先保存脚本')
  }
}

// ─────────────── params schema helpers ───────────────
function addParam() {
  form.value.params_schema.push({
    key: `param${form.value.params_schema.length + 1}`,
    type: 'int',
    min: 1, max: 100, step: 1, default: 10,
    valuesStr: '',
  })
}

function onValuesStrChange(row) {
  if (row.type !== 'choice') return
  const parts = (row.valuesStr || '').split(',').map(s => s.trim()).filter(Boolean)
  row.values = parts.map(p => {
    const n = Number(p)
    return Number.isFinite(n) ? n : p
  })
}

function _formToPayload(f) {
  return {
    name: f.name,
    code: f.code,
    description: f.description,
    status: f.status,
    params_schema: f.params_schema.map(p => {
      const out = { key: p.key, type: p.type }
      if (p.type === 'choice') {
        out.values = p.values || []
        if (p.default !== undefined) out.default = p.default
      } else {
        out.min = p.min
        out.max = p.max
        out.step = p.step
        out.default = p.default
      }
      return out
    }),
  }
}

// ─────────────── editor: 简单行号同步 ───────────────
function syncScroll(e) {
  const lineNos = e.target.parentElement.querySelector('.sd-line-numbers')
  if (lineNos) lineNos.scrollTop = e.target.scrollTop
}

// ─────────────── mount ───────────────
onMounted(async () => {
  await loadScripts()
})
</script>

<style scoped>
.script-dev-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.sd-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-4);
}
.sd-title { margin: 0; font-size: 18px; font-weight: 600; }

.sd-body {
  display: flex;
  flex: 1;
  gap: var(--space-4);
  min-height: 0;
}

.sd-pane {
  background: var(--bg-elevated);
  border-radius: var(--radius-md);
  padding: var(--space-4);
  overflow: auto;
}
.sd-pane-left { width: 280px; flex-shrink: 0; }
.sd-pane-right { flex: 1; display: flex; flex-direction: column; gap: var(--space-3); min-width: 0; }
.sd-pane-empty { display: grid; place-items: center; min-height: 400px; }

.sd-section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  margin: 0 0 var(--space-3);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.sd-empty {
  text-align: center;
  color: var(--text-placeholder);
  padding: var(--space-6) 0;
}

.sd-script-list { list-style: none; padding: 0; margin: 0; }
.sd-script-list li {
  padding: var(--space-3);
  border-radius: var(--radius-sm);
  cursor: pointer;
  margin-bottom: 4px;
  transition: background var(--transition-fast);
}
.sd-script-list li:hover { background: var(--bg-hover); }
.sd-script-list li.active {
  background: var(--brand-gradient-soft);
  color: var(--brand-primary);
}
.sd-filter { margin-bottom: var(--space-2); }
.sd-script-owner { font-size: 11px; color: var(--color-text-tertiary); }
.sd-script-name { font-weight: 500; margin-bottom: 4px; }
.sd-script-meta {
  display: flex;
  gap: var(--space-2);
  align-items: center;
  font-size: 11px;
  color: var(--text-secondary);
}

/* 编辑器 */
.sd-editor-wrap { flex: 1; display: flex; flex-direction: column; min-height: 0; }
.sd-editor-label {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: var(--space-2);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.sd-editor-hint { font-size: 11px; color: var(--text-placeholder); font-weight: normal; text-transform: none; letter-spacing: 0; }

.sd-editor {
  flex: 1;
  display: flex;
  border: 1px solid var(--border-base);
  border-radius: var(--radius-sm);
  overflow: hidden;
  background: #1e1e1e;
  min-height: 400px;
  max-height: 60vh;
}
.sd-line-numbers {
  flex-shrink: 0;
  width: 50px;
  background: #252526;
  color: #858585;
  font-family: var(--font-mono, 'Menlo', monospace);
  font-size: 13px;
  line-height: 1.5;
  padding: var(--space-3) var(--space-2);
  text-align: right;
  overflow: hidden;
  user-select: none;
}
.sd-line-no { line-height: 1.5; }
.sd-textarea {
  flex: 1;
  background: #1e1e1e;
  color: #d4d4d4;
  font-family: var(--font-mono, 'Menlo', monospace);
  font-size: 13px;
  line-height: 1.5;
  padding: var(--space-3);
  border: none;
  outline: none;
  resize: none;
  white-space: pre;
  overflow: auto;
  tab-size: 4;
}

/* params */
.sd-params { flex-shrink: 0; }
.sd-params-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: var(--space-2);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.sd-hint { font-size: 11px; color: var(--text-placeholder); }

.sd-footer {
  display: flex;
  gap: var(--space-2);
  justify-content: flex-end;
  border-top: 1px solid var(--border-light);
  padding-top: var(--space-3);
}

/* 移动端 */
@media (max-width: 768px) {
  .sd-body { flex-direction: column; }
  .sd-pane-left { width: 100%; max-height: 200px; }
}
</style>