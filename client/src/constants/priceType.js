/**
 * 价格类型常量
 * 与后端 / 柜台 (xtconstant) 协议保持一致
 *
 * v__: 协议重对齐 — 由原 5/11/14/44 (4 选) 简化为 0/1/2 (3 选)
 *   - FIX_PRICE = 0       xtconstant.FIX_PRICE                 (限价 / 指定价)
 *   - LATEST_PRICE = 1    xtconstant.LATEST_PRICE              (最新价)
 *   - MARKET_PEER_PRICE_FIRST = 2  xtconstant.MARKET_PEER_PRICE_FIRST  (市价 / 对手方最优价, 吃档 1)
 */
export const PriceType = {
  // 柜台协议数字码 (xtconstant)
  FIX_PRICE: 0,                    // 限价 (指定价)
  LATEST_PRICE: 1,                 // 最新价
  MARKET_PEER_PRICE_FIRST: 2,      // 市价 (对手方最优价, 吃档 1)

  // 短别名 (历史命名, 保持兼容避免破坏外部引用)
  LIMIT: 0,        // == FIX_PRICE (限价)
  LATEST: 1,       // == LATEST_PRICE (最新价)
  MARKET: 2,       // == MARKET_PEER_PRICE_FIRST (市价)

  // 人类可读标签
  LABEL: {
    0: "限价",
    1: "最新价",
    2: "市价",
  },

  /**
   * 将代码转为标签，未知代码返回代码本身
   */
  label(code) {
    return this.LABEL[code] || String(code);
  },

  /**
   * 默认价格类型（限价单）
   */
  default() {
    return this.FIX_PRICE;
  },
};

/**
 * 订单类型常量
 */
export const OrderType = {
  BUY: "23",   // 买入
  SELL: "24",  // 卖出
};

/**
 * 价格类型选项（用于 el-radio-button）
 * v__: 3 个按钮 — 限价 (0) / 最新价 (1) / 市价 (2), 与 xtconstant 协议 1:1 对齐
 */
export const priceTypeOptions = [
  { label: '限价', value: PriceType.FIX_PRICE },                    // 0
  { label: '最新价', value: PriceType.LATEST_PRICE },               // 1
  { label: '市价', value: PriceType.MARKET_PEER_PRICE_FIRST },      // 2
];
