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
    - AdminStockConfig   : 同上
-->
<template>
    <!-- v28-10: 回退 wrapper 包裹层结构; 用 unscoped <style> block + 加 :scp- 前缀避免污染 -->
    <div class="scp-wrapper" :style="wrapperStyle">
        <div class="scp-code-input" :style="codeInputStyle">
            <el-autocomplete
                v-model="inputText"
                :placeholder="placeholder || '输入代码 / 名称 / 首字母'"
                :disabled="disabled"
                :clearable="clearable"
                :size="size"
                :trigger-on-focus="triggerOnFocus"
                :fetch-suggestions="querySearch"
                value-key="stock_code"
                class="scp-code-autocomplete"
                @select="onSelectItem"
                @blur="onBlur"
            >
                <template #default="{ item }">
                    <div class="scp-row">
                        <span class="scp-code text-mono">{{ item.stock_code }}</span>
                        <span class="scp-name" v-t0-badge="item.stock_code">{{ item.stock_name }}</span>
                        <span v-if="item.short_name" class="scp-short">
                            [{{ item.short_name }}]
                        </span>
                    </div>
                </template>
            </el-autocomplete>
        </div>
        <div class="scp-tag-box">
            <el-tag
                v-if="selectedStock"
                :type="tagType"
                :size="size"
                disable-transitions
                class="scp-tag"
            >
                <span v-t0-badge="selectedStock.stock_code">{{ selectedStock.stock_name }}</span>
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
let lastApplyTs = 0                                  // v53: 外部程序化填入时间戳, 防 blur 竞态
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
    flex: `0 0 ${inputBasisPercent.value}%`,  // 贴一起后无需 - 4px, gap=0 时两边之和正好 100%
    width: `${inputBasisPercent.value}%`,
    minWidth: 0,
}))

const tagBoxStyle = computed(() => ({
    flex: `0 0 calc(${100 - inputBasisPercent.value}% + 1px)`,  // v28-8: 多吃 1px 抵消左 wrapper 的 inset shadow 1px
    width: `calc(${100 - inputBasisPercent.value}% + 1px)`,     // 同时给 width 防 flex-basis 退化
    minWidth: 0,
}))

// 缓存 initCache promise (避免并发触发, 复用 v27 模式)
let cacheLoadPromise = null
async function ensureCache() {
    if (store.cacheLoaded) return
    if (cacheLoadPromise) return cacheLoadPromise
    cacheLoadPromise = store.initCache().catch((e) => {
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
    // v113: 空 query 也返结果 (默认弹全量前 N 条), 不再"不输入无候选"
    //   旧行为: inputText 为空时 cb([]) → autocomplete 无候选 → 用户看不到任何股票
    //   新行为: 空 query 返 cache 前 50 条, 鼓励用户直接看到列表选
    const results = queryString
        ? store.searchCache(queryString, 50)
        : store.searchCache('', 50)  // 空 query 走 searchCache 默认分支 (全部)
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
    // v53: 如果刚被外部程序化填入, 500ms 内忽略 blur 清空 (避免 dblclick → blur 竞态)
    if (Date.now() - lastApplyTs < 500) return
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
 * 外部程序化填入股票代码 (绕过 cache lookup + blur 竞态)
 * 供 OrderForm.onExternalApplyStockCode 调用
 */
function applyStockCode(code) {
    const c = String(code || '').trim().toUpperCase()
    lastApplyTs = Date.now()
    if (!c) {
        inputText.value = ''
        selectedStock.value = null
        return
    }
    const matched = store.cacheMap.get(c)
    if (matched) {
        selectedStock.value = matched
        inputText.value = matched.stock_code
        emit('update:modelValue', matched.stock_code)
        emit('select', matched)
    } else {
        // cache 里没有也填入 inputText, 让用户可手动编辑
        inputText.value = c
        selectedStock.value = null
        emit('update:modelValue', c)
    }
}
defineExpose({ applyStockCode })

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
        const matched = store.cacheMap.get(newVal)
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
            const matched = store.cacheMap.get(props.modelValue)
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
    /* 这是包裹层 div, 拿 flex-basis, 不透传到内部 el-input */
    min-width: 0;
    box-sizing: border-box;
    display: flex;  /* 让内 el-autocomplete 自适应 */
}

.scp-code-autocomplete {
    /* el-autocomplete 自身撑满父容器 */
    width: 100%;
    display: flex;
    align-items: stretch;
}

/* v28-7: el-autocomplete 内部所有相关层都要清右半圆角,
   element-plus 结构 .el-autocomplete > .el-input > .el-input__wrapper > .el-input__inner,
   wrapper 默认 box-shadow: inset 1px 模拟边框 (项目里 el-border-radius-base=8)
   必须多层覆盖, 才能呈现"两个直角"
*/
/* v28-19: 强制 .el-input 从 inline-flex 改 flex, 消除 baseline 偏移
   实测 v28-18: el-input display:inline-flex vertical-align:middle
   inline-flex 在 block 父容器内 baseline 计算偏移约 1.30px, 导致 el-input__inner top=175.09
   vs placeholder top=173.80
   改成 flex 后 box top = parent top, 文字 top 也对齐
*/
.scp-code-autocomplete :deep(.el-input) {
    display: flex !important;
    vertical-align: top !important;
}
.scp-code-autocomplete :deep(.el-input),
.scp-code-autocomplete :deep(.el-input__wrapper),
.scp-code-autocomplete :deep(.el-input__inner) {
    border-top-right-radius: 0 !important;
    border-bottom-right-radius: 0 !important;
}

/* v28-7: 默认 + focus 状态 box-shadow 都吃透明, 让 el-input__wrapper 没有 inset border,
   视觉上不会出现"双 1px 阴影线" */
.scp-code-autocomplete :deep(.el-input__wrapper),
.scp-code-autocomplete :deep(.el-input__wrapper.is-focus),
.scp-code-autocomplete :deep(.el-input__wrapper:hover),
.scp-code-autocomplete :deep(.el-input__wrapper:focus-within) {
    box-shadow: 0 0 0 1px var(--el-input-border-color, #dcdfe6) inset, 0 0 0 0 transparent !important;
    border-top-right-radius: 0 !important;
    border-bottom-right-radius: 0 !important;
}

/* hover/focus 时用 primary 色 outline 而非 box-shadow, 避免线膨胀 */
.scp-code-autocomplete :deep(.el-input__wrapper:hover) {
    box-shadow: 0 0 0 1px var(--el-color-primary-light-5, #c0d4f7) inset !important;
}
.scp-code-autocomplete :deep(.el-input__wrapper:focus-within),
.scp-code-autocomplete :deep(.el-input__wrapper.is-focus) {
    box-shadow: 0 0 0 1px var(--el-color-primary, #409eff) inset !important;
}

.scp-tag-box {
    /* 宽度由 inline style (tagBoxStyle) 控制 */
    flex: 0 0 calc(50% + 1px);  /* v28-8: 多吃 1px 用来遮盖左 wrapper 的 inset shadow 1px, 衔接处无缝 */
    margin-left: -1px;  /* v28-8: 把这 1px 抵消, 总宽不变 */
    min-width: 0;
    box-sizing: border-box;
    display: flex;
    align-items: stretch;
    /* v28-8: 用 box-shadow inset 1px 模拟边框, 与 el-input__wrapper 同款, 让两段视觉是一个 input-group */
    border: none;
    box-shadow: 0 0 0 1px var(--el-input-border-color, #dcdfe6) inset !important;
    border-top-left-radius: 0 !important;
    border-bottom-left-radius: 0 !important;
    border-top-right-radius: var(--el-border-radius-base, 8px) !important;
    border-bottom-right-radius: var(--el-border-radius-base, 8px) !important;
    /* v28-17: 让 input 文字 baseline 与 placeholder 对齐
   实测 v28-16: inner_top=175.09 placeholder_top=173.80 差 1.30px
   原因: el-input__inner 默认 line-height: normal (~16px), 文字 baseline 在 input 元素内略下偏
   placeholder line-height: 30px, 文字 baseline 在 30px 元素中部

   修复: 强制 el-input__inner line-height: 30px (跟 placeholder 一致)
*/
.scp-code-autocomplete :deep(.el-input__inner) {
    line-height: 30px !important;
}

/* v28-14: 修正垂直对齐 + box-shadow 重叠区颜色统一
   实测 v28-13:
     wrap_box_shadow: rgb(232, 237, 245) inset 1px (--border-light, 项目 main.css)
     tag_box_shadow:  rgb(220, 223, 230) inset 1px (--el-input-border-color, element-plus 默认)
     两色在 1px 重叠区形成"双线夹一缝"视觉

   修复策略:
   - font-size: 13px 跟 el-input__inner 一致 (避免字号 14px vs 13px 让文字偏上)
   - padding/line-height 调整让 placeholder 文字 top 与 inner top 差 ≤ 0.5px
   - box-shadow 改用项目 main.css 同色 --border-light (rgb(232,237,245)), 让两段 border 颜色一致
   - 实际效果: 中间衔接 1px 重叠处视觉上只有一条线, 跟委托价/数量一致
*/
    padding: 1px 11px;
    height: 33px;  /* v28-18: 跟 .scp-code-input 等高 (el-autocomplete 内部 el-input 默认 33px 高) */
    font-size: 13px !important;  /* v28-15: 强制 13px, 跟左 input 一致 */
    line-height: 30px;
    box-shadow: 0 0 0 1px rgb(232, 237, 245) inset !important;  /* v28-15: hard-code 同色, 避免 var(--border-light) 找不到 */
    background: var(--el-fill-color-light, #f5f7fa);
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
    font-size: 13px !important;  /* v28-16: 跟左 input 字号一致 (v28-15 写在父 .scp-tag-box 没生效, 14px 在此覆盖) */
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

/* v28-10: UNSCOPED global block
   scp-code-autocomplete 是 <el-autocomplete> 子组件内部元素,
   Vue scoped 只给当前组件 root 加 data-v-xxx, 不会传给子组件元素,
   所以 :deep() 编译后生成的 [data-v-xxx] .el-input__wrapper 无法 match.

   解决方案: 用 unscoped <style> block + 以 .scp-code-autocomplete class 为命名空间,
   项目内 99% 的 el-autocomplete 不会带这个 class, 不会污染全局
*/
</style>

<style>
/* v28-20: UNSCOPED (此块必须 unscoped, 因为 .scp-code-autocomplete 是 <el-autocomplete> 组件元素,
   Vue scoped 只给当前组件 root element 加 data-v, 子组件元素不带 data-v,
   所以 scoped 选择器 .scp-code-autocomplete[data-v-xxx] .el-input 永远匹配不上)
   specificity: (0,2,0) > element-plus .el-input (0,1,0)
*/
/* v28-19: 强制 .el-input 从 inline-flex 改 flex, 消除 baseline 偏移
   实测: el-input display:inline-flex vertical-align:middle → baseline 偏移 1.30px
   改 flex 后 el-input top 与父容器 top 一致, 文字 top 也对齐
*/
.scp-code-autocomplete .el-input {
    display: flex !important;
    vertical-align: top !important;
}
.scp-code-autocomplete .el-input__wrapper,
.scp-code-autocomplete .el-input,
.scp-code-autocomplete .el-input__inner {
    border-top-right-radius: 0 !important;
    border-bottom-right-radius: 0 !important;
}
.scp-code-autocomplete .el-input__wrapper,
.scp-code-autocomplete .el-input__wrapper.is-focus,
.scp-code-autocomplete .el-input__wrapper:focus-within {
    box-shadow: 0 0 0 1px var(--el-input-border-color, #dcdfe6) inset !important;
}
.scp-code-autocomplete .el-input__wrapper:hover {
    box-shadow: 0 0 0 1px var(--el-color-primary-light-5, #c0d4f7) inset !important;
}
.scp-code-autocomplete .el-input__wrapper:focus-within,
.scp-code-autocomplete .el-input__wrapper.is-focus {
    box-shadow: 0 0 0 1px var(--el-color-primary, #409eff) inset !important;
}
</style>
