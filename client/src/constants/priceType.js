/**
 * 价格类型常量 — 与柜台协议码点对齐
 *   - FIX_PRICE = 11       xtconstant.FIX_PRICE                  (限价 / 指定价)
 *   - LATEST_PRICE = 5     xtconstant.LATEST_PRICE               (最新价)
 *   - MARKET_PEER_PRICE_FIRST = 44  xtconstant.MARKET_PEER_PRICE_FIRST  (市价 / 对手方最优价, 吃档 1)
 *
 */
export const PriceType = {
  // 柜台协议数字码 (xtconstant)
  FIX_PRICE: 11,                   // 限价 (指定价)
  LATEST_PRICE: 5,                 // 最新价
  MARKET_PEER_PRICE_FIRST: 44,     // 市价 (对手方最优价, 吃档 1)

  // 短别名 (历史命名, 保持兼容避免破坏外部引用)
  LIMIT: 11,       // == FIX_PRICE (限价)
  LATEST: 5,       // == LATEST_PRICE (最新价)
  MARKET: 44,      // == MARKET_PEER_PRICE_FIRST (市价)

  // 人类可读标签
  LABEL: {
    11: "限价",
    5: "最新价",
    44: "市价",
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
 * 3 个按钮 — 限价 (11) / 最新价 (5) / 市价 (44), 与 xtconstant 协议 1:1 对齐
 */
export const priceTypeOptions = [
  { label: '限价', value: PriceType.FIX_PRICE },                    // 11
  { label: '最新价', value: PriceType.LATEST_PRICE },               // 5
  { label: '市价', value: PriceType.MARKET_PEER_PRICE_FIRST },      // 44
];
