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
    11: "限价",       // 备用: 不在 UI 暴露, 仅保留给历史数据 / 后端 fallback 解析
    14: "限价",       // 原"挂单价" — UI 重命名 (送参数 code 仍 14, 不变)
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
 * 价格类型选项（用于 el-radio-button）
 * v__: "限价" UI 实际送 value=14 (挂单价/对手价)，底层 code 不变
 */
export const priceTypeOptions = [
  { label: '限价', value: PriceType.OPPONENT },  // 14 原"挂单价"
  { label: '最新价', value: PriceType.LATEST },  // 5
  { label: '市价', value: PriceType.MARKET },    // 44
];
