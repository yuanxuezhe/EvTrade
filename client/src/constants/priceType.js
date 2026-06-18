/**
 * 价格类型常量
 * 与后端/柜台协议保持一致
 */
export const PriceType = {
  // 柜台协议数字码
  LATEST: 5,       // 最新价
  LIMIT: 11,       // 指定价 (限价)
  OPPONENT: 14,    // 挂单价 (对手价)
  MARKET: 44,      // 市价

  // 人类可读标签
  LABEL: {
    5: "最新价",
    11: "限价",
    14: "挂单价",
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
    return this.LIMIT;
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
 * 价格类型选项（用于 el-segmented）
 */
export const priceTypeOptions = [
  { label: '限价', value: PriceType.LIMIT },
  { label: '最新价', value: PriceType.LATEST },
  { label: '挂单价', value: PriceType.OPPONENT },
  { label: '市价', value: PriceType.MARKET },
];
