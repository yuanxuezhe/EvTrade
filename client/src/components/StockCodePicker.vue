<!--
  StockCodePicker.vue — 证券代码选择器 (v28, 任务: 2026-07-XX-stock-code-picker)

  数据源: useStocksStore.cache (全量 5529, 内存, 跨页面共享)
  筛选:   stock_code 前缀 > short_name 前缀 > stock_name 包含 (复用 v27 评分算法)
  视觉:   左 50% el-autocomplete 输入框 / 右 50% el-tag 显示名称 (只读, 不可关闭)

  与 v27 StockCodeAutocomplete 的关键区别 (契约变更):
    - v-model 严格语义: 只有"从候选中真正选中"才是 stock_code 的有效值
    - 未选中 (输入框打字未选 / 改输其他代码) 时, blur 会自动 emit('') 清空 v-model
    - 这样避免下游(下单/查询)拿到"用户手打到一半的非法代码"
    - 父组件使用方式兼容 v27: v-model="stock_code" + @select="(s)=>{stock_name = s.stock_name}"

  Props:
    - modelValue   (string)        : v-model stock_code (only "600519.SH", 不含名称)
    - placeholder  (string)        : 输入框占位符
    - disabled     (boolean)       : 是否禁用
    - clearable    (boolean)       : 可清空
    - size         (string)        : 'default' | 'small' | 'large'
    - tagType      (string)        : el-tag type (success/info/warning/danger/primary), 默认 primary
    - width        (string|number) : 组件整体宽度, 默认 '100%' (如 '420px' / 420), 与委托价同行宽
    - inputRatio   (number)        : 左(代码)占比权重, 默认 1
    - nameRatio    (number)        : 右(名称)占比权重, 默认 1
                                      → 默认 50/50 平分; inputRatio=2,nameRatio=1 → 66.7%/33.3%
                                      (归一化百分比, 不要求两值相加==某数)

  Emits:
    - update:modelValue (string)   : stock_code 变化 (只在 selectedStock 有效时 emit 非空)
    - select           (stock)     : 用户从候选中选中, item 为完整 stock 对象
    - blur             ()          : 失焦 (此时若输入框值与已选 code 不一致, emit('') 自动清空)

  使用场景 (v28 上线, 试水点: OrderForm.vue 即 Trade.vue 下单):
    - OrderForm.vue      : v-model="form.stock_code", @select 写 form.stock_name
    - T0TaskCreateDialog : 同上
    - StrategyConfig     : 同上
    - AdminStockConfig   : 同上
-->
<template>
    <div class="scp-wrapper" :style="wrapperStyle">
        <!-- 左: 代码输入 (el-autocomplete, 宽度由 flex-basis 控制) -->
        <el-autocomplete
            v-model="inputText"
            :placeholder="placeholder || '输入代码 / 名称 / 首字母'"
            :disabled="disabled"
            :clearable="clearable"
            :size="size"
            :trigger-on-focus="triggerOnFocus"
            :fetch-suggestions="querySearch"
            value-key="stock_code"
            class="scp-code-input"
            :style="codeInputStyle"
            @select="onSelectItem"
            @blur="onBlur"
        >
            <template #default="{ item }">
                <div class="scp-row">
                    <span class="scp-code text-mono">{{ item.stock_code }}</span>
                    <span class="scp-name">{{ item.stock_name }}</span>
                    <span v-if="item.short_name" class="scp-short">
                        [{{ item.short_name }}]
                    </span>
                </div>
            </template>
        </el-autocomplete>

        <!-- 右: 名称展示 (el-tag, 只读, 宽度由 flex-basis 控制) -->
        <div class="scp-tag-box" :style="tagBoxStyle">
            <el-tag
                v-if="selectedStock"
                :type="tagType"
                :size="size"
                disable-transitions
                class="scp-tag"
            >
                {{ selectedStock.stock_name }}
            </el-tag>
            <span v-else class="scp-tag-placeholder">请选择股票</span>
        </div>
    </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useStocksStore } from '../stores/stocks'

const props = defineProps({
    modelValue: { type: String, default: '' },
    placeholder: { type: String, default: '' },
    disabled: { type: Boolean, default: false },
    clearable: { type: Boolean, default: true },
    triggerOnFocus: { type: Boolean, default: false },
    size: { type: String, default: 'default' },
    tagType: { type: String, default: 'primary' },
    // v28-2: 容器整体宽度 (支持 '100%' / '420px' / 420 数字), 默认 '100%' 与 OrderForm 委托价/数量同行宽
    width: { type: [String, Number], default: '100%' },
    // v28-2: 左右占比 (相对比例, 自动归一化为百分比), 默认 50/50 (即"55开"理解为"50:50 平分")
    inputRatio: { type: Number, default: 1 },
    nameRatio: { type: Number, default: 1 },
})

const emit = defineEmits(['update:modelValue', 'select', 'blur'])

const store = useStocksStore()

// 内部状态 (单一可信源)
const inputText = ref(props.modelValue || '')        // 输入框值 (含用户打字未选中间态)
const selectedStock = ref(null)                      // 已选 stock 对象 (唯一可信源, 决定 v-model)
// 默认占位符 (可由 props.placeholder 覆盖)
const namePlaceholder = '请选择股票'

/**
 * v28-2 宽度/占比计算:
 *   - wrapperStyle.width: props.width 数字→px, 字符串→原样
 *   - inputBasisPercent / nameBasisPercent: 归一化后百分比 (分配 flex-basis)
 *   - 保证 inputRatio:nameRatio=0 也安全 (输入框 0%,名称 100% 会撑爆,所以加 max(1, ...) 兜底)
 */
const wrapperStyle = computed(() => {
    const w = typeof props.width === 'number' ? `${props.width}px` : props.width
    return { width: w }
})

const inputBasisPercent = computed(() => {
    const total = Math.max(0.0001, props.inputRatio + props.nameRatio)
    return (props.inputRatio / total) * 100
})

const codeInputStyle = computed(() => ({
    flex: `0 0 calc(${inputBasisPercent.value}% - 4px)`,  // 4px = gap 一半
    width: `calc(${inputBasisPercent.value}% - 4px)`,
    minWidth: 0,
}))

const tagBoxStyle = computed(() => ({
    flex: `0 0 calc(${100 - inputBasisPercent.value}% - 4px)`,
    width: `calc(${100 - inputBasisPercent.value}% - 4px)`,
    minWidth: 0,
}))

// 缓存 loadCache promise (避免并发触发, 复用 v27 模式)
let cacheLoadPromise = null
async function ensureCache() {
    if (store.cacheLoaded) return
    if (cacheLoadPromise) return cacheLoadPromise
    cacheLoadPromise = store.loadCache().catch((e) => {
        cacheLoadPromise = null
        throw e
    })
    return cacheLoadPromise
}

/**
 * el-autocomplete fetch-suggestions
 * 复用 v27 评分算法: code 前缀 > short_name 前缀 > name 包含
 */
async function querySearch(queryString, cb) {
    try {
        await ensureCache()
    } catch (e) {
        cb([])
        return
    }
    const results = store.searchCache(queryString, 50)
    cb(results)
}

/**
 * 从候选中真正选中
 * v28 契约: 只有这里 emit 的值才是 v-model 的"有效值"
 */
function onSelectItem(item) {
    if (!item || !item.stock_code) return
    selectedStock.value = item
    inputText.value = item.stock_code
    emit('update:modelValue', item.stock_code)
    emit('select', item)
}

/**
 * el-autocomplete 输入变化
 * v28 语义: 不在这里 emit update:modelValue (避免"打字未选"算有效值)
 * 只在 selectedStock.code 一致时 emit (维持 v-model 同步)
 */
watch(inputText, (newVal) => {
    if (selectedStock.value && selectedStock.value.stock_code === newVal) {
        // 选中后输入框等于已选 code (正常同步), 维持 emit
        emit('update:modelValue', newVal)
    }
})

/**
 * blur 处理 (v28 核心契约)
 * 若当前输入框值 !== 已选 stock_code, 视为"未选中/改输", emit('') 清空
 */
function onBlur() {
    emit('blur')
    const typed = inputText.value || ''
    if (!selectedStock.value) {
        // 当前就未选, 若输入框非空 (打字未选) 就清掉 (以防 v-model 还残留)
        if (typed && props.modelValue !== '') {
            inputText.value = ''
            emit('update:modelValue', '')
        }
        return
    }
    // 已选状态: 输入框与已选 code 一致 → OK; 不一致 → 清空 + emit('')
    if (typed !== selectedStock.value.stock_code) {
        inputText.value = ''
        selectedStock.value = null
        emit('update:modelValue', '')
    }
}

/**
 * 同步父组件 v-model → 内部状态
 * (场景: 父组件 defaultStockCode 预填 / 重置表单)
 */
watch(
    () => props.modelValue,
    (newVal) => {
        if (!newVal) {
            // 父组件清空 → 重置内部
            inputText.value = ''
            selectedStock.value = null
            return
        }
        const matched = store.cache.find((s) => s.stock_code === newVal)
        if (matched) {
            selectedStock.value = matched
            inputText.value = matched.stock_code
        } else {
            // 父组件给了无效 code, 清掉内部但保留已选 (避免误清)
            inputText.value = ''
            selectedStock.value = null
        }
    }
)

/**
 * cache 加载完后, 若 props.modelValue 命中 cache 自动同步 (复用 v27 模式)
 */
watch(
    () => store.cacheLoaded,
    (loaded) => {
        if (loaded && props.modelValue) {
            const matched = store.cache.find(
                (s) => s.stock_code === props.modelValue
            )
            if (matched && (!selectedStock.value || selectedStock.value.stock_code !== matched.stock_code)) {
                selectedStock.value = matched
                inputText.value = matched.stock_code
            }
        }
    },
    { immediate: true }
)
</script>

<style scoped>
/* v28-3: 输入框和名称框贴一起, 视觉对齐 el-input-number (与委托价/数量同行宽)
   策略: 删 wrapper gap = 8px → 0; el-autocomplete / 名称框 都各自带 element-plus input 同款边框,
         但 border-radius 一左一右, 形成"连续控件"
*/
.scp-wrapper {
    display: flex;
    gap: 0;  /* 贴一起 */
    align-items: stretch;
    width: 100%;
    box-sizing: border-box;
}

.scp-code-input {
    /* 宽度由 inline style (codeInputStyle) 控制 */
    min-width: 0;
    box-sizing: border-box;
    display: flex;
    align-items: stretch;
}

/* v28-3: el-autocomplete 内部 el-input wrapper, 调成"左圆右直" */
.scp-code-input :deep(.el-input__wrapper) {
    border-top-right-radius: 0;
    border-bottom-right-radius: 0;
}

.scp-tag-box {
    /* 宽度由 inline style (tagBoxStyle) 控制 */
    min-width: 0;
    display: flex;
    align-items: stretch;  /* 等高, 跟输入框对齐 */
    box-sizing: border-box;
    border: 1px solid var(--el-border-color, #dcdfe6);
    border-left: none;  /* 中间无缝 */
    border-top-right-radius: var(--el-border-radius-base, 4px);
    border-bottom-right-radius: var(--el-border-radius-base, 4px);
    padding: 1px 11px;  /* 仿 el-input 内边距 */
    height: var(--el-input-height, 32px);
    background: var(--el-fill-color-light, #f5f7fa);  /* 微微区分"只读"区域 */
    color: var(--el-text-color-regular, #606266);
}

.scp-tag {
    width: 100%;
    border: none;
    background: transparent !important;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
}

.scp-tag :deep(.el-tag__content) {
    width: 100%;
    text-align: center;
}

.scp-tag-placeholder {
    color: var(--el-text-color-placeholder, #a8abb2);
    font-size: 14px;
    padding-left: 12px;
}

.scp-row {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
}

.scp-code {
    color: var(--el-color-primary, #409eff);
    font-weight: 600;
    min-width: 90px;
}

.scp-name {
    flex: 1;
    color: var(--el-text-color-primary, #303133);
}

.scp-short {
    color: var(--el-text-color-secondary, #909399);
    font-family: var(--font-mono, 'JetBrains Mono', 'Consolas', monospace);
    font-size: 11px;
}

.text-mono {
    font-family: var(--font-mono, 'JetBrains Mono', 'Consolas', monospace);
}
</style>
