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
        <el-alert
          v-if="isReadonly"
          type="warning"
          :closable="false"
          show-icon
          title="他人公开脚本 · 只读"
          description="可查看源码与参数, 但无权修改。可据此新建自己的策略。"
          class="sd-ro-banner"
          data-el="sd-readonly-banner"
        />
        <!-- 顶部表单 -->
        <div class="sd-form">
          <el-form :inline="true" label-width="80px">
            <el-form-item label="脚本名">
              <el-input v-model="form.name" placeholder="如: ma_cross_v1" style="width: 220px" :disabled="isReadonly" data-el="sd-name" />
            </el-form-item>
            <el-form-item label="状态">
              <el-select v-model="form.status" style="width: 120px" :disabled="isReadonly">
                <el-option label="active" value="active" />
                <el-option label="paused" value="paused" />
              </el-select>
            </el-form-item>
            <el-form-item label="描述">
              <el-input v-model="form.description" placeholder="(可选)" style="width: 300px" :disabled="isReadonly" />
            </el-form-item>
          </el-form>
        </div>

        <!-- 代码编辑器 -->
        <div class="sd-editor-wrap">
          <div class="sd-editor-label">
            <span>脚本源码</span>
            <span style="display:flex; gap:12px; align-items:center">
              <span class="sd-editor-hint">
                实现 on_init / on_bar / on_tick / on_finish 回调, 可调 MA/EMA/RSI/doorder 等
              </span>
              <!-- 2026-08-20: 代码编辑器最大化按钮 (切换编辑器填满剩余空间 + 折叠参数表) -->
              <el-button
                :icon="editorExpanded ? Aim : FullScreen"
                size="small"
                plain
                @click="editorExpanded = !editorExpanded"
                :title="editorExpanded ? '收起编辑器' : '最大化编辑器'"
                data-el="sd-editor-toggle"
              >
                {{ editorExpanded ? '收起' : '最大化' }}
              </el-button>
            </span>
          </div>
          <div class="sd-editor" :class="{ expanded: editorExpanded }">
            <!-- 2026-08-20: 改用 CodeMirror 6 通用组件 (python 语法高亮 + 自动缩进) -->
            <CodeEditor
              v-model="form.code"
              :read-only="isReadonly"
              placeholder="# 在此编写策略代码"
              data-el="sd-code"
            />
          </div>
        </div>

        <!-- 参数 schema -->
        <!-- 2026-08-20: 展开编辑器时折叠 params 表格成 summary 风格, 给编辑器腾位置 -->
        <details v-if="!editorExpanded" class="sd-params-details" open>
          <summary class="sd-params-head">
            <span>参数 schema ({{ form.params_schema.length }})</span>
            <span style="display:flex; gap:12px; align-items:center">
              <el-button :icon="Plus" size="small" plain :disabled="isReadonly" @click.stop="addParam" data-el="sd-add-param">
                新增参数
              </el-button>
              <span class="sd-editor-hint">▾ 点击收起参数表</span>
            </span>
          </summary>
          <el-table :data="form.params_schema" size="small" border>
            <el-table-column label="key" width="100">
              <template #default="{ row }">
                <el-input v-model="row.key" size="small" placeholder="key" :disabled="isReadonly" />
              </template>
            </el-table-column>
            <el-table-column label="类型" width="100">
              <template #default="{ row }">
                <el-select v-model="row.type" size="small" :disabled="isReadonly">
                  <el-option label="int" value="int" />
                  <el-option label="float" value="float" />
                  <el-option label="choice" value="choice" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="min" width="90">
              <template #default="{ row }">
                <el-input-number v-if="row.type !== 'choice'" v-model="row.min" size="small" :step="row.type === 'int' ? 1 : 0.1" :disabled="isReadonly" />
              </template>
            </el-table-column>
            <el-table-column label="max" width="90">
              <template #default="{ row }">
                <el-input-number v-if="row.type !== 'choice'" v-model="row.max" size="small" :step="row.type === 'int' ? 1 : 0.1" :disabled="isReadonly" />
              </template>
            </el-table-column>
            <el-table-column label="step" width="80">
              <template #default="{ row }">
                <el-input-number v-if="row.type !== 'choice'" v-model="row.step" size="small" :step="0.1" :min="0.001" :disabled="isReadonly" />
              </template>
            </el-table-column>
            <el-table-column label="default" width="90">
              <template #default="{ row }">
                <el-input-number v-if="row.type !== 'choice'" v-model="row.default" size="small" :disabled="isReadonly" />
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
                  :disabled="isReadonly"
                  @change="onValuesStrChange(row)"
                />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="60" align="center">
              <template #default="{ $index }">
                <el-button :icon="Delete" size="small" link type="danger" :disabled="isReadonly" @click="form.params_schema.splice($index, 1)" />
              </template>
            </el-table-column>
          </el-table>
        </details>

        <!-- 底部按钮 -->
        <div class="sd-footer">
          <el-button @click="onCancel" data-el="sd-cancel">取消</el-button>
          <el-button :icon="Delete" v-if="form.id" type="danger" :disabled="isReadonly" @click="onDelete" data-el="sd-delete">删除</el-button>
          <el-button :icon="Document" type="primary" :loading="saving" :disabled="isReadonly" @click="onSave" data-el="sd-save">
            保存
          </el-button>
          <!-- 2026-08-21: 编译按钮 — 静态语法检查（ast.parse）不跑回测 -->
          <el-button :icon="DocumentChecked" type="warning" :loading="compiling" :disabled="isReadonly || !form.id" @click="onCompile" data-el="sd-compile">
            编译
          </el-button>
          <el-button :icon="VideoPlay" type="success" :loading="testing" :disabled="isReadonly" @click="onTestBacktest" data-el="sd-test">
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
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Delete, Document, DocumentChecked, VideoPlay, FullScreen, Aim } from '@element-plus/icons-vue'
import { scriptStrategyApi } from '../api/script_strategy'
import { useAuthStore } from '../stores/auth'
import CodeEditor from '../components/cells/CodeEditor.vue'  // 2026-08-20: CodeMirror 6 封装 (python 语法高亮 + 自动缩进)

const router = useRouter()

// ─────────────── state ───────────────
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const compiling = ref(false)  // 2026-08-21: 编译按钮 loading 态
// 2026-08-20: 编辑器最大化开关 — 折叠参数表让编辑器撑满
const editorExpanded = ref(false)
const scripts = ref([])
const selectedId = ref(null)
const selectedUserId = ref(null)  // v90+: 复合 PK (user_id, id)
const currentScript = ref(null)
const draft = ref(null)  // 新建未保存
const filterMode = ref('all')     // v90+: 'all' / 'mine' / 'public'
const currentUserId = ref(null)   // 从 user store 拿当前用户 ID

const form = ref(_blankForm())

// 2026-08-20: lineCount / syncScroll / editorTab 缩进 等均改由 CodeMirror 内置, 不再手写
const isReadonly = computed(() =>
  currentScript.value != null && currentScript.value.user_id !== currentUserId.value
)

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
    // 记录当前用户 ID (单一来源: auth store, 用于显示 owner tag / 只读判定)
    currentUserId.value = Number(useAuthStore().user?.id) || null
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
  // 拉默认模板 (失败时 fallback inline demo, 避免空白不能编辑)
  let tpl = null
  try {
    tpl = await scriptStrategyApi.getDefaultTemplate()
  } catch (e) {
    // 拦截器已弹 — 但给用户一个可用 demo, 不让编辑器空白
    tpl = null
  }
  const defaultCode = (tpl && typeof tpl.code === 'string' && tpl.code)
    ? tpl.code
    : FALLBACK_DEMO_CODE
  const defaultParams = (tpl && Array.isArray(tpl.params_schema) && tpl.params_schema.length)
    ? tpl.params_schema
    : FALLBACK_DEMO_PARAMS
  // 2026-08-21 fix: 不要整体替换 form.value — el-table 内部对 params_schema 数组
  //   持有 vnode ref, 整体替换会导致 patchElement 报 'Cannot set properties of
  //   null (setting __vnode)' (select.vue:407)。改用增量字段更新, 保持 ref 引用。
  form.value.id = null
  form.value.name = ''
  form.value.description = ''
  form.value.status = 'active'
  form.value.code = defaultCode
  // params_schema 必须 splice 清空再 push (保持 ref 引用, 触发 el-table 内部响应)
  form.value.params_schema.splice(0, form.value.params_schema.length, ...defaultParams.map(p => ({
    ...p,
    valuesStr: Array.isArray(p.values) ? p.values.join(',') : '',
  })))
  selectedId.value = null
  currentScript.value = null
  draft.value = { name: 'new' }
}

// 2026-08-21: 后端 /templates/default 失败 (或返回空) 时的兜底 demo
//   让用户点新建后立刻看到可编辑的 python 代码 + 示例参数,
//   避免编辑器空白 + 无法编辑给用户造成"按钮坏了"错觉
const FALLBACK_DEMO_CODE = `# 简易均线交叉策略 (demo)
# 实现 on_bar 回调: 短均线上穿长均线 → 买, 下穿 → 卖

def on_init(context):
    context.fast_ma = []
    context.slow_ma = []
    context.pos = 0

def on_bar(context, bar):
    fast_period = context.params.fast   # 参数: 短均线周期
    slow_period = context.params.slow   # 参数: 长均线周期
    qty = context.params.qty            # 参数: 下单数量

    context.fast_ma.append(bar.close)
    if len(context.fast_ma) > fast_period:
        context.fast_ma.pop(0)
    context.slow_ma.append(bar.close)
    if len(context.slow_ma) > slow_period:
        context.slow_ma.pop(0)

    if len(context.fast_ma) < fast_period or len(context.slow_ma) < slow_period:
        return

    fast = sum(context.fast_ma) / fast_period
    slow = sum(context.slow_ma) / slow_period

    if fast > slow and context.pos <= 0:
        doorder(context.stock_code, qty, bar.close)
        context.pos += qty
    elif fast < slow and context.pos > 0:
        doorder(context.stock_code, -context.pos, bar.close)
        context.pos = 0
`

const FALLBACK_DEMO_PARAMS = [
  { key: 'fast', type: 'int', min: 3, max: 30, step: 1, default: 5 },
  { key: 'slow', type: 'int', min: 10, max: 120, step: 1, default: 20 },
  { key: 'qty', type: 'int', min: 100, max: 10000, step: 100, default: 100 },
]

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

async function onTestBacktest() {
  // 跳到 ScriptTask 页面并自动选择该脚本
  if (form.value.id) {
    router.push({ path: '/script-task', query: { script_id: form.value.id } })
  } else {
    ElMessage.warning('请先保存脚本')
  }
}

// 2026-08-21: 编译按钮 handler — 调后端 POST /scripts/{id}/compile 做 ast.parse 静态校验
async function onCompile() {
  if (!form.value.id) {
    ElMessage.warning('请先保存脚本')
    return
  }
  compiling.value = true
  try {
    const result = await scriptStrategyApi.compileScript(form.value.id)
    if (result.ok) {
      ElMessage.success('语法 OK')
    } else {
      const { line, col, msg } = result.error || {}
      await ElMessageBox.alert(msg || '语法错误', `语法错误 (line ${line}, col ${col})`, { type: 'error' })
    }
  } catch (e) {
    // axios 拦截器已弹
  } finally {
    compiling.value = false
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

// ─────────────── editor: 行号/缩进全部由 CodeMirror 内置 (2026-08-20 抽组件) ───────────────
// 旧手写 syncScroll / onEditorTab / onEditorShiftTab / onEditorEnter 已删除
// (codemirror 6 自带行号侧栏 + 当前行高亮 + Python 自动缩进 + 括号匹配)

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
/* 2026-08-20: 最大化编辑器 — 撑满 sd-pane-right 剩余空间, 不再卡 60vh */
.sd-editor.expanded {
  flex: 1;
  max-height: none;
  min-height: 0;
  height: 100%;
}
.sd-line-numbers {
  /* 2026-08-20: 改用 CodeMirror 内置行号侧栏, 这些手写 CSS 保留无害但不再生效 */
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

/* params */
.sd-params { flex-shrink: 0; }
/* 2026-08-20: params 改 details/summary, summary 始终可见 (表头), 表格可点 summary 折叠 */
.sd-params-details {
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  background: var(--bg-card);
}
.sd-params-details > summary {
  list-style: none;
  cursor: pointer;
  padding: var(--space-2) var(--space-3);
  user-select: none;
}
.sd-params-details > summary::-webkit-details-marker { display: none; }
.sd-params-details[open] > summary { border-bottom: 1px solid var(--border-light); margin-bottom: var(--space-2); }
.sd-params-details > summary:hover { background: var(--bg-hover); }
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
.sd-ro-banner { margin-bottom: var(--space-3); }

/* 移动端 */
@media (max-width: 768px) {
  .sd-body { flex-direction: column; }
  .sd-pane-left { width: 100%; max-height: 200px; }
}
</style>