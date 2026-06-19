# Spec Delta — frontend

新增 REQ-FE-011 / REQ-FE-012 到 `openspec/specs/frontend/spec.md`：

## REQ-FE-011: T0 敞口表组件
- 文件：`client/src/views/T0Trade.vue` 内置组件
- 数据源：`t0StatsApi.getExposure({ user_def: 'T0' })`
- 列：代码 / 买量 / 卖量 / 净量 / 净额 / 委托数 / 状态
- 操作列：一键配平按钮（按 `net_volume` 符号选买卖方向，volume=|net_volume|，price=latest）
- 排序：按 abs(net_amount) 降序

## REQ-FE-012: T0 累计收益卡片
- 文件：`client/src/views/T0Trade.vue` 内置卡片
- 数据源：`t0StatsApi.getAggregate({ user_def: 'T0', days })`
- 字段：累计已实现 / 回报率 / 胜率 / 胜总天数 / 笔数 / 股票数
- 时间窗口切换：7/30/90 天
