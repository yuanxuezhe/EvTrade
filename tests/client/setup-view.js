/**
 * setup-view.js — view-level 测试基础设施 (change: add-view-level-vitest-stack)
 *
 * 提供:
 *   - Element Plus 组件 stub (只 stub 用到的子组件, 保留 Vue 渲染流程)
 *   - vue-router stub (memory history + 可断言 mock)
 *   - pinia 自动隔离 (beforeEach setActivePinia)
 *   - global.mountView / global.flushPromises helpers
 *
 * 用法 (在 view 测试文件头部):
 *   // @vitest-environment jsdom
 *   import '../setup-view'  // 自动 register vi.mock + beforeEach + global
 *   import { mountView, flushPromises } from '../setup-view'  // 也可显式 import
 *
 * 注意: setup 文件本身不写 describe/it, 只注册基础设施
 */
// @vitest-environment jsdom
import { vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

// ─── Element Plus 组件 stub ──────────────────────────────────────
// 保留 Vue 渲染流程: props / slots / emits
// 不模拟 Element Plus 内部状态机 (el-table 列宽等由 jsdom + ResizeObserver 处理)

// ─── Element Plus icons stub ─────────────────────────────────────
// 所有 icon 渲染为空 div (测试只关心 click handler, 不关心 icon 渲染)
vi.mock('@element-plus/icons-vue', () => {
  const makeIcon = (name) => ({ name, template: '<i class="el-icon-stub" />' })
  // 列出 view 测试用到的 icon (按需扩展 — 覆盖 client/src 全量 import)
  const ICONS = [
    'Search', 'Refresh', 'Download', 'Plus', 'Delete', 'Edit', 'Close', 'Check',
    'ArrowUp', 'ArrowDown', 'ArrowRight', 'Top', 'Bottom', 'Minus',
    'List', 'Document', 'Files', 'InfoFilled', 'Warning', 'Setting', 'Operation',
    'Lock', 'User', 'UserFilled', 'SwitchButton', 'Menu', 'Fold', 'Expand',
    'Sunny', 'Moon', 'View', 'VideoPlay', 'EditPen',
    'Money', 'Wallet', 'Coin', 'Box', 'Tickets', 'Cpu', 'Odometer',
    'DataAnalysis', 'DataBoard', 'DataLine', 'TrendCharts', 'PieChart',
    'CaretTop', 'CaretBottom',
  ]
  const stub = {}
  for (const n of ICONS) stub[n] = makeIcon(n)
  return stub
})

// ─── 共享 stub 工厂 ──────────────────────────────────────────────
// 必须在 vi.mock 工厂外部定义, 否则引用不到
function makeStub(name, additionalProps = []) {
  const kebab = name.replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase()
  return {
    name,
    template: `<div class="${kebab}"
      :class="[type ? '${kebab}--' + type : '', size ? '${kebab}--' + size : '']"
      :data-el="'${name}'"
      :disabled="disabled || null"
      :loading="loading || null">
      <slot />
    </div>`,
    props: ['modelValue', 'data', 'prop', 'label', 'width', 'align',
      'fixed', 'sortable', 'showOverflowTooltip', 'type', 'size',
      'sizeOf', 'placement', 'trigger', 'title', 'disabled', 'loading',
      'plain', 'round', 'circle', 'link', 'text', 'bg', 'icon',
      'pageSizes', 'total', 'currentPage', 'pageSize', 'layout',
      'small', 'background', 'pagerCount', 'prevText', 'nextText',
      'description', 'imageSize', 'dateValue', 'valueFormat',
      'startPlaceholder', 'endPlaceholder', 'typeOf',
      'span', 'titleOf', 'border', 'column', 'direction',
      'labelOf', 'valueOf',
      ...additionalProps]
  }
}

// el-table-column: 占位 stub, 不渲染 slot 内容
const ElTableColumnStub = {
  name: 'ElTableColumn',
  template: `<div class="el-tablecolumn" :data-el="'ElTableColumn'" :data-prop="prop" :data-label="label" />`,
  props: ['prop', 'label', 'width', 'align', 'fixed', 'sortable', 'showOverflowTooltip', 'minWidth', 'type'],
}

// el-table: 遍历 data 渲染行, 每行用 <slot :row> 传递上下文
const ElTableStub = {
  name: 'ElTable',
  template: `<div class="el-table" :data-el="'ElTable'">
    <div v-for="(row, idx) in (data || [])" :key="idx" class="el-table-row" :data-row-idx="idx">
      <slot :row="row" :$index="idx" :column="{ property: '' }" />
    </div>
    <slot name="empty" />
  </div>`,
  props: ['data', 'defaultSort', 'showOverflowTooltip', 'stripe', 'size', 'maxHeight', 'style'],
}

const ElPaginationStub = {
  name: 'ElPagination',
  template: `<div class="el-pagination" :data-el="'ElPagination'">
    <button class="page-btn-prev" @click="$emit('current-change', currentPage - 1)">prev</button>
    <span class="page-current">{{ currentPage }}</span>
    <button class="page-btn-next" @click="$emit('current-change', currentPage + 1)">next</button>
  </div>`,
  props: ['total', 'currentPage', 'pageSize', 'pageSizes', 'layout', 'small', 'background', 'pagerCount', 'prevText', 'nextText'],
  emits: ['current-change', 'size-change', 'update:currentPage', 'update:pageSize'],
}

const ElFormStub = {
  name: 'ElForm',
  template: `<form class="el-form" :data-el="'ElForm'" @submit.prevent="$emit('submit')"><slot /></form>`,
  props: ['model', 'rules', 'labelWidth', 'inline', 'size'],
  emits: ['submit'],
}

const ElFormItemStub = {
  name: 'ElFormItem',
  template: `<div class="el-form-item" :data-el="'ElFormItem'" :data-prop="prop"><slot /></div>`,
  props: ['prop', 'label', 'rules', 'required', 'error'],
}

const ElInputStub = {
  name: 'ElInput',
  template: `<input class="el-input" :data-el="'ElInput'" :value="modelValue" @input="$emit('update:modelValue', $event.target.value)" />`,
  props: ['modelValue', 'type', 'placeholder', 'clearable', 'disabled', 'style', 'size', 'readonly', 'step', 'min', 'max', 'precision', 'controls', 'controlsPosition'],
  emits: ['update:modelValue', 'change', 'input', 'clear'],
}

const ElInputNumberStub = {
  name: 'ElInputNumber',
  template: `<input class="el-input-number" :data-el="'ElInputNumber'" type="number" :value="modelValue" @input="$emit('update:modelValue', Number($event.target.value))" />`,
  props: ['modelValue', 'min', 'max', 'step', 'precision', 'placeholder', 'disabled', 'style', 'size', 'controls', 'controlsPosition'],
  emits: ['update:modelValue', 'change', 'input'],
}

const ElCheckboxStub = {
  name: 'ElCheckbox',
  template: `<input class="el-checkbox" :data-el="'ElCheckbox'" type="checkbox" :checked="modelValue" @change="$emit('update:modelValue', $event.target.checked)" />`,
  props: ['modelValue', 'label', 'disabled', 'trueLabel', 'falseLabel'],
  emits: ['update:modelValue', 'change'],
}

const ElDatePickerStub = {
  name: 'ElDatePicker',
  template: `<input class="el-date-editor" :data-el="'ElDatePicker'" :value="modelValue" @input="$emit('update:modelValue', $event.target.value)" />`,
  props: ['modelValue', 'type', 'rangeSeparator', 'startPlaceholder', 'endPlaceholder',
          'valueFormat', 'format', 'clearable', 'editable', 'disabledDate', 'style'],
  emits: ['update:modelValue', 'change'],
}

vi.mock('element-plus', async () => {
  // 注意: vi.mock 工厂只能引用外部 vi 等, 重新定义 makeStub 在工厂内
  const makeStubInside = (name, additionalProps = []) => ({
    name,
    template: `<div class="${name.toLowerCase()}" :data-el="'${name}'"><slot /></div>`,
    props: ['modelValue', 'data', 'prop', 'label', 'width', 'align',
      'fixed', 'sortable', 'showOverflowTooltip', 'type', 'size',
      'sizeOf', 'placement', 'trigger', 'title', 'disabled', 'loading',
      'plain', 'round', 'circle', 'link', 'text', 'bg', 'icon',
      'pageSizes', 'total', 'currentPage', 'pageSize', 'layout',
      'small', 'background', 'pagerCount', 'prevText', 'nextText',
      'description', 'imageSize', 'dateValue', 'valueFormat',
      'startPlaceholder', 'endPlaceholder', 'typeOf',
      'span', 'titleOf', 'border', 'column', 'direction',
      'labelOf', 'valueOf',
      ...additionalProps]
  })

  // el-table-column: 占位 stub, 不渲染 slot 内容 (避免 slot scope 嵌套问题)
// 测试主要断言 wrapper.vm 状态 + class 选择器, 不需要 el-table-column 的实际渲染
  const ElTableColumnStub = {
    name: 'ElTableColumn',
    template: `<div class="el-tablecolumn" :data-el="name" :data-prop="prop" :data-label="label" />`,
    props: ['prop', 'label', 'width', 'align', 'fixed', 'sortable', 'showOverflowTooltip', 'minWidth', 'type'],
  }

  // el-table: 遍历 data 渲染行, 每行用 <slot :row> 传递上下文 (供消费者模板 #default="{ row }")
  const ElTableStub = {
    name: 'ElTable',
    template: `<div class="el-table" :data-el="name">
      <div v-for="(row, idx) in (data || [])" :key="idx" class="el-table-row" :data-row-idx="idx">
        <slot :row="row" :$index="idx" :column="{ property: '' }" />
      </div>
      <slot name="empty" />
    </div>`,
    props: ['data', 'defaultSort', 'showOverflowTooltip', 'stripe', 'size', 'maxHeight', 'style'],
  }

  // el-pagination: emit current-change / size-change 给 @event 用
  const ElPaginationStub = {
    name: 'ElPagination',
    template: `<div class="el-pagination" :data-el="name">
      <button class="page-btn-prev" @click="$emit('current-change', currentPage - 1)">prev</button>
      <span class="page-current">{{ currentPage }}</span>
      <button class="page-btn-next" @click="$emit('current-change', currentPage + 1)">next</button>
    </div>`,
    props: ['total', 'currentPage', 'pageSize', 'pageSizes', 'layout', 'small', 'background', 'pagerCount', 'prevText', 'nextText'],
    emits: ['current-change', 'size-change', 'update:currentPage', 'update:pageSize'],
  }

  // el-form: 透传 slot
  const ElFormStub = {
    name: 'ElForm',
    template: `<form class="el-form" :data-el="name" @submit.prevent="$emit('submit')"><slot /></form>`,
    props: ['model', 'rules', 'labelWidth', 'inline', 'size'],
    emits: ['submit'],
  }

  const ElFormItemStub = {
    name: 'ElFormItem',
    template: `<div class="el-form-item" :data-el="name" :data-prop="prop"><slot /></div>`,
    props: ['prop', 'label', 'rules', 'required', 'error'],
  }

  // el-input: emit update:modelValue (v-model)
  const ElInputStub = {
    name: 'ElInput',
    template: `<input class="el-input" :data-el="name" :value="modelValue" @input="$emit('update:modelValue', $event.target.value)" />`,
    props: ['modelValue', 'type', 'placeholder', 'clearable', 'disabled', 'style', 'size', 'readonly', 'step', 'min', 'max', 'precision', 'controls', 'controlsPosition'],
    emits: ['update:modelValue', 'change', 'input', 'clear'],
  }

  // el-input-number: 数字输入, emit Number
  const ElInputNumberStub = {
    name: 'ElInputNumber',
    template: `<input class="el-input-number" :data-el="name" type="number" :value="modelValue" @input="$emit('update:modelValue', Number($event.target.value))" />`,
    props: ['modelValue', 'min', 'max', 'step', 'precision', 'placeholder', 'disabled', 'style', 'size', 'controls', 'controlsPosition'],
    emits: ['update:modelValue', 'change', 'input'],
  }

  // el-checkbox: emit update:modelValue
  const ElCheckboxStub = {
    name: 'ElCheckbox',
    template: `<input class="el-checkbox" :data-el="name" type="checkbox" :checked="modelValue" @change="$emit('update:modelValue', $event.target.checked)" />`,
    props: ['modelValue', 'label', 'disabled', 'trueLabel', 'falseLabel'],
    emits: ['update:modelValue', 'change'],
  }

  // el-date-picker: emit update:modelValue
  const ElDatePickerStub = {
    name: 'ElDatePicker',
    template: `<input class="el-date-editor" :data-el="name" :value="modelValue" @input="$emit('update:modelValue', $event.target.value)" />`,
    props: ['modelValue', 'type', 'rangeSeparator', 'startPlaceholder', 'endPlaceholder',
            'valueFormat', 'format', 'clearable', 'editable', 'disabledDate', 'style'],
    emits: ['update:modelValue', 'change'],
  }

  const ElMessage = {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  }
  // ElMessageBox 默认 resolve 'confirm' (等价用户点确认)
  const ElMessageBox = {
    confirm: vi.fn().mockResolvedValue('confirm'),
    alert: vi.fn().mockResolvedValue('alert'),
    prompt: vi.fn().mockResolvedValue({ value: '' }),
  }
  const ElNotification = vi.fn()

  return {
    default: {
      ElButton: makeStub('ElButton'),
      ElTable: ElTableStub,
      ElTableColumn: ElTableColumnStub,
      ElPagination: ElPaginationStub,
      ElInput: ElInputStub,
      ElInputNumber: ElInputNumberStub,
      ElForm: ElFormStub,
      ElFormItem: ElFormItemStub,
      ElDialog: makeStub('ElDialog'),
      ElDrawer: makeStub('ElDrawer'),
      ElTag: makeStub('ElTag'),
      ElEmpty: makeStub('ElEmpty'),
      ElPopover: makeStub('ElPopover'),
      ElTooltip: makeStub('ElTooltip'),
      ElIcon: makeStub('ElIcon'),
      ElDatePicker: ElDatePickerStub,
      ElSelect: makeStub('ElSelect'),
      ElOption: makeStub('ElOption'),
      ElCheckbox: ElCheckboxStub,
      ElCheckboxGroup: makeStub('ElCheckboxGroup'),
      ElRadioGroup: makeStub('ElRadioGroup'),
      ElRadioButton: makeStub('ElRadioButton'),
      ElRadio: makeStub('ElRadio'),
      ElCard: makeStub('ElCard'),
      ElAlert: makeStub('ElAlert'),
      ElRow: makeStub('ElRow'),
      ElCol: makeStub('ElCol'),
      ElScrollbar: makeStub('ElScrollbar'),
      ElDescriptions: makeStub('ElDescriptions'),
      ElDescriptionsItem: makeStub('ElDescriptionsItem'),
      ElDivider: makeStub('ElDivider'),
      ElProgress: makeStub('ElProgress'),
      ElSwitch: makeStub('ElSwitch'),
      ElSlider: makeStub('ElSlider'),
      ElMessage,
      ElMessageBox,
      ElNotification,
    },
    ElMessage,
    ElMessageBox,
    ElNotification,
  }
})

// ─── vue-router stub ─────────────────────────────────────────────
// 用 memory history 创建可 push/replace 的 router
// 用户测试可断言 router.push 被调

let _testRouter = null
vi.mock('vue-router', async () => {
  const actual = await vi.importActual('vue-router')
  return {
    ...actual,
    useRouter: () => _testRouter || {
      push: vi.fn(),
      replace: vi.fn(),
      go: vi.fn(),
      back: vi.fn(),
      forward: vi.fn(),
      currentRoute: { value: { path: '/', params: {}, query: {} } }
    },
    useRoute: () => ({
      params: {},
      query: {},
      path: '/',
      fullPath: '/',
      name: undefined,
      meta: {},
    })
  }
})

// ─── pinia 自动隔离 ─────────────────────────────────────────────
let _activePinia = null
beforeEach(() => {
  _activePinia = createPinia()
  setActivePinia(_activePinia)
  _testRouter = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: { template: '<div />' } }]
  })
})

afterEach(() => {
  _activePinia = null
  _testRouter = null
})

// ─── global helpers ─────────────────────────────────────────────

// Element Plus 组件名 → stub 映射 (用于 global.components 注册)
const _elStubs = {
  ElButton: makeStub('ElButton'),
  ElTable: ElTableStub,
  ElTableColumn: ElTableColumnStub,
  ElPagination: ElPaginationStub,
  ElInput: ElInputStub,
  ElInputNumber: ElInputNumberStub,
  ElForm: ElFormStub,
  ElFormItem: ElFormItemStub,
  ElDialog: makeStub('ElDialog'),
  ElDrawer: makeStub('ElDrawer'),
  ElTag: makeStub('ElTag'),
  ElEmpty: makeStub('ElEmpty'),
  ElPopover: makeStub('ElPopover'),
  ElTooltip: makeStub('ElTooltip'),
  ElIcon: makeStub('ElIcon'),
  ElDatePicker: ElDatePickerStub,
  ElSelect: makeStub('ElSelect'),
  ElOption: makeStub('ElOption'),
  ElCheckbox: ElCheckboxStub,
  ElCheckboxGroup: makeStub('ElCheckboxGroup'),
  ElRadioGroup: makeStub('ElRadioGroup'),
  ElRadioButton: makeStub('ElRadioButton'),
  ElRadio: makeStub('ElRadio'),
  ElCard: makeStub('ElCard'),
  ElAlert: makeStub('ElAlert'),
  ElRow: makeStub('ElRow'),
  ElCol: makeStub('ElCol'),
  ElScrollbar: makeStub('ElScrollbar'),
  ElDescriptions: makeStub('ElDescriptions'),
  ElDescriptionsItem: makeStub('ElDescriptionsItem'),
  ElDivider: makeStub('ElDivider'),
  ElProgress: makeStub('ElProgress'),
  ElSwitch: makeStub('ElSwitch'),
  ElSlider: makeStub('ElSlider'),
}

/**
 * 挂载 view 组件, pinia 自动注册, Element Plus 自动 stub
 * @param {Object} component - SFC or options object
 * @param {Object} [opts]
 * @param {Object} [opts.props] - 组件 props
 * @param {Object} [opts.slots] - 命名 slots
 * @param {Object} [opts.stubs] - 覆盖默认 stub (例如 stub 整个子组件)
 * @returns {VueWrapper}
 */
global.mountView = function mountView(component, { props = {}, slots = {}, stubs = {} } = {}) {
  return mount(component, {
    props,
    slots,
    global: {
      plugins: [_activePinia],
      // Element Plus 组件通过 global.components 注册 (kebab-case 名 → stub)
      components: _elStubs,
      stubs: { ...stubs },
      // 屏蔽未注册指令警告
      directives: {
        loading: { mounted() {}, updated() {} }
      }
    }
  })
}

global.flushPromises = flushPromises

// named exports (方便显式 import)
export { mountView, flushPromises }
export const __testRouter = () => _testRouter