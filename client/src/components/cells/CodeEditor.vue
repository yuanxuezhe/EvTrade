<!--
  CodeEditor.vue — CodeMirror 6 封装的 Python 代码编辑器 (2026-08-20 / v2 2026-08-21)

  设计目标:
    - 替换 ScriptDev.vue 内裸 textarea, 获得语法高亮 / 自动缩进 / 括号匹配
    - 单文件组件, 异步加载 codemirror (ESM dynamic import, 不阻塞页面)
    - v-model 双向绑定 code 字符串
    - 行号侧栏 + 当前行高亮 (codemirror 内置)
    - 支持只读 (readOnly)
    - 主题: one-dark (与原 textarea 黑色风格一致)

  v2 修复:
    - 把所有 import 的 codemirror 扩展提升到 script setup 顶层 (静态 import, 不再闭包陷阱)
    - 把 readOnly 编辑性配置改成单一 EditorView.editable.of (React 风格)
    - 改用 simple ref 跟踪 EditorView, 避免 shallowRef 引用问题
    - modelValue 同步逻辑: 直接 dispatch transaction with setContents (而不是 replace range)

  Props:
    modelValue   String   必填, v-model 绑定
    readOnly     Boolean  默认 false
    placeholder  String   占位文字

  Emits:
    update:modelValue   内容变化
-->
<template>
  <div class="code-editor" :data-el="dataEl">
    <div ref="containerRef" class="code-editor-mount" />
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, watch, markRaw } from 'vue'
// 静态 import — 顶层加载, 避免在 _mount 闭包内引用
import { EditorView, basicSetup } from 'codemirror'
import { EditorState, Compartment } from '@codemirror/state'
import { lineNumbers, highlightActiveLine, keymap } from '@codemirror/view'
import { indentUnit } from '@codemirror/language'
import { python } from '@codemirror/lang-python'
import { oneDark } from '@codemirror/theme-one-dark'

const props = defineProps({
  modelValue: { type: String, default: '' },
  readOnly: { type: Boolean, default: false },
  placeholder: { type: String, default: '' },
  dataEl: { type: String, default: 'code-editor' },
})
const emit = defineEmits(['update:modelValue'])

const containerRef = ref(null)
// markRaw: codemirror EditorView 含内部劫持对象, 不放响应式避免 Vue 反复代理
const editorView = ref(null)



onMounted(() => {
  if (!containerRef.value) return
  const state = EditorState.create({
    doc: props.modelValue || '',
    extensions: _buildExtensions(),
  })
  editorView.value = markRaw(new EditorView({
    state,
    parent: containerRef.value,
  }))
  // 焦点: 让编辑器可立刻输入 (新建脚本场景)
  if (!props.readOnly) {
    setTimeout(() => editorView.value?.focus(), 50)
  }
})

// 外部 modelValue 变化 (切换脚本 / 默认模板加载) → 同步到编辑器
watch(() => props.modelValue, (newVal) => {
  if (!editorView.value) return
  const cur = editorView.value.state.doc.toString()
  if (cur === newVal) return
  // 用 transaction 而不是 createState, 保留 undo history
  editorView.value.dispatch({
    changes: { from: 0, to: cur.length, insert: newVal || '' },
  })
})

// readOnly 切换 — 用 Compartment 包 editable (codelens 标准做法)
//   后续可加 watch(readOnly, ...) 用 compartment.reconfigure 切换
const editableCompartment = new Compartment()
const readonlyCompartment = new Compartment()

function _buildExtensions() {
  return [
    // 缩进 (PEP 8: 4 空格) — codemirror 默认 indentUnit=2, 必须显式覆盖
    // basicSetup 已含 indentOnInput + defaultKeymap + bracketMatching + foldGutter,
    // 这里只补 indentUnit
    indentUnit.of('    '),
    basicSetup,
    lineNumbers(),
    highlightActiveLine(),
    python(),
    oneDark,
    editableCompartment.of(EditorView.editable.of(!props.readOnly)),
    readonlyCompartment.of(EditorState.readOnly.of(props.readOnly)),
    EditorView.contentAttributes.of({ spellcheck: 'false' }),
    EditorView.updateListener.of((vu) => {
      if (vu.docChanged) emit('update:modelValue', vu.state.doc.toString())
    }),
  ]
}

onBeforeUnmount(() => {
  if (editorView.value) {
    editorView.value.destroy()
    editorView.value = null
  }
})
</script>

<style scoped>
.code-editor {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
  border-radius: var(--radius-sm);
  background: #1e1e1e;
}
.code-editor-mount {
  width: 100%;
  height: 100%;
}
</style>

<style>
/* codemirror 自身样式 (非 scoped, 因为 shadow DOM 注入) */
.cm-editor {
  height: 100%;
  font-size: 13px;
  font-family: var(--font-mono, 'Menlo', 'Consolas', monospace);
}
.cm-editor.cm-focused { outline: none !important; }
.cm-scroller { font-family: inherit; line-height: 1.5; }
.cm-gutters {
  background: #252526 !important;
  border-right: 1px solid #333 !important;
  color: #858585 !important;
}
.cm-content { padding: 8px 0 !important; }
</style>
