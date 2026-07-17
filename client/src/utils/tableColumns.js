/**
 * tableColumns.js — 通用 el-table-column 列样式常量 (v69 抽出)
 *
 * 设计目标:
 *   - 把"列类型 + 宽度 + 对齐 + 文本类"的样板抽出来, 表格模板只写业务 prop/label
 *   - "字典各自自个定义": 每种业务字典自带自己的常量, 互不耦合
 *   - 渐进式迁移: 新表直接用, 老表 (T0Trade.vue / HistoryOrders.vue) 下轮再说
 *
 * 6 类常量:
 *   1. STOCK_CODE   — 证券代码 (单列, mono + tp-stock-code)
 *   2. STOCK_TARGET — 标的 (代码+名称合并, 仿 T0Trade.vue 标的列)
 *   3. TIME         — 时间 (下单时间/委托时间, 容纳 String(23) "YYYY-MM-DD HH:MM:SS.fff")
 *   4. NUMBER       — 数量 (成交量/委托量/撤单量, 千分位 mono 右对齐)
 *   5. MONEY        — 价格/金额 (委托价/成交均价/成交金额, 2 位小数 mono 右对齐)
 *   6. DICT         — 字典翻译 (工厂函数, 传入 dict map + 可选 formatter 来自定义样式)
 *
 * 用法 (TodayOrdersPanel.vue 范例):
 *   import { COL } from '../../utils/tableColumns'
 *   <el-table-column prop="volume" label="委托量" sortable v-bind="COL.NUMBER" />
 *   <el-table-column label="方向" v-bind="COL.DICT(ORDER_TYPE_LABEL, { width: 60 })" />
 *
 * 注意:
 *   - 这些常量只是属性集合 (label/width/align/headerAlign), 不含业务模板
 *   - 业务模板 (formatMoney / stockName 等) 仍在调用方手写
 *   - sortable / show-overflow-tooltip 等业务属性由调用方叠加 (不进常量)
 */

/**
 * 1. STOCK_CODE — 证券代码单列
 *    适用: 单列显示 stock_code, 不含名称
 *    模板: <span class="text-mono tp-stock-code">{{ row.xxx }}</span>
 */
export const STOCK_CODE = {
  width: 100,
  align: 'left',
  headerAlign: 'left',
}

/**
 * 2. STOCK_TARGET — 标的 (代码+名称合并)
 *    适用: 单列显示 stock_code + 名称 (仿 T0Trade.vue 标的列)
 *    模板: 参见 T0Trade.vue 主表标的列 (text-mono 代码 + 6px + text-secondary 名称)
 *    width 用 min-width (名称长度可变, 让列自然撑宽)
 */
export const STOCK_TARGET = {
  minWidth: 140,
  align: 'left',
  headerAlign: 'left',
}

/**
 * 3. TIME — 时间列 (下单时间/委托时间)
 *    适用: 容纳 String(23) "YYYY-MM-DD HH:MM:SS.fff" 全显
 *    width=185: 23 字符 mono + 8px 左右 padding
 *    模板: <span class="text-mono text-secondary">{{ row.xxx }}</span>
 */
export const TIME = {
  width: 185,
  align: 'left',
  headerAlign: 'left',
}

/**
 * 4. NUMBER — 数量列
 *    适用: 委托量/成交量/撤单量
 *    模板: <span class="text-mono">{{ formatNumber(row.xxx) }}</span>
 */
export const NUMBER = {
  width: 100,
  align: 'right',
  headerAlign: 'right',
}

/**
 * 5. MONEY — 价格/金额列
 *    适用: 委托价/成交均价/成交金额
 *    模板: <span class="text-mono">{{ formatMoney(row.xxx) }}</span>
 */
export const MONEY = {
  width: 100,
  align: 'right',
  headerAlign: 'right',
}

/**
 * 6. DICT — 字典翻译 (工厂函数)
 *    适用: 把后端字典码翻译成中文 (方向/状态/价格类型 等)
 *    "字典各自自个定义": 每种字典自带自己的常量, 通过 makeDict 工厂生成
 *
 * @param {Object} dict - 字典 map, 例 { '23': '买入', '24': '卖出' }
 * @param {Object} [overrides] - 调用方覆盖默认样式, 例 { width: 60 }
 * @returns {Object} 列属性集合
 *
 * 模板 (调用方):
 *   <template #default="{ row }">
 *     <span>{{ ORDER_TYPE_LABEL[row.xxx] || row.xxx }}</span>
 *   </template>
 *
 * 内置字典常量 (按业务领域分, 各 dict 自己定义自己的列样式):
 */

/** 委托方向 (23买/24卖) — chip 风格 + 颜色 */
export const DIRECTION = makeDict('DIRECTION', {
  width: 60,
  align: 'center',
  headerAlign: 'center',
})

/** 委托状态 (broker 码 → 中文) — chip 风格, 已由 OrderStatusBadge 封装, 这里只管列属性 */
export const STATUS = makeDict('STATUS', {
  width: 100,
  align: 'center',
  headerAlign: 'center',
})

/** 价格类型 (5最新价/11限价/14对手价/44市价) — 轻量字典, 纯文本 */
export const PRICE_TYPE = makeDict('PRICE_TYPE', {
  width: 80,
  align: 'left',
  headerAlign: 'left',
})

/** 通用字典 — 当内置字典常量不合适时, 用 DICT() 工厂自定义 */
export function makeDict(_name, defaults = {}) {
  return {
    width: defaults.width ?? 90,
    align: defaults.align ?? 'right',
    headerAlign: defaults.headerAlign ?? 'right',
    // 允许调用方完全覆盖
    ...defaults,
  }
}

/**
 * 一站式聚合导出 (调用方默认走这个, 避免逐个 import)
 */
export const COL = {
  STOCK_CODE,
  STOCK_TARGET,
  TIME,
  NUMBER,
  MONEY,
  DIRECTION,
  STATUS,
  PRICE_TYPE,
  makeDict,
}