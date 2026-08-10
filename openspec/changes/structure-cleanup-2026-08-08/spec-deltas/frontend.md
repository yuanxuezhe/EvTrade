## MODIFIED Requirements

### Requirement: 前端 API 层 HTTP 基础设施与业务 endpoint 分离

`client/src/api/index.js`（338 行）此前同时承载三类职责：axios 实例 + 拦截器 + RPC 解包
（横切关注点）和 20+ 个业务 endpoint 方法（领域关注点）。本 change 将其拆为两个文件，
使横切基础设施与业务 endpoint 各自单一职责。

#### 变更前（spec 现状）

spec L144：「入口 `client/src/api/index.js` 导出 axios 实例」

#### 变更后

- `client/src/api/http.js`（~110 行）：导出 `http`（axios 实例）、`tokenStorage`、
  `setUnauthorizedHandler`。内含请求/响应拦截器、RPC `{code,msg,list}` 解包逻辑、
  401 处理。**横切基础设施，被所有 per-feature API 文件依赖。**
- `client/src/api/index.js`（~220 行）：只保留 `export const api = { ... }` 业务 endpoint
  方法（getHoldings/getOrders/createOrder/...）。从 `./http` 导入 `http`。
- spec L144 改为：「入口 `client/src/api/http.js` 导出 axios 实例；`client/src/api/index.js`
  导出业务 endpoint 聚合对象 `api`」

#### Scenario: per-feature API 文件导入 http 实例

- **WHEN** `api/strategy.js` / `api/script_strategy.js` / `api/stocks.js` / `api/t0_tasks.js` /
  `api/t0_stats.js` / `api/admin.js` / `api/sysconfig.js` / `api/sync.js` 需要 axios 实例
- **THEN** 导入路径为 `import { http } from './http'`（同目录）或 `import { http } from '../api/http'`（views/components 跨目录）
- **AND** 不再从 `./index` 或 `../api` 导入 `http`

#### Scenario: 拦截器行为不变

- **WHEN** 任意 API 请求返回 RPC 响应 `{code: 0, msg, list}`
- **THEN** 拦截器解包为 `list` 数组，调用方 `await http.get(...)` 拿到数组
- **AND** 401 响应触发 `setUnauthorizedHandler` 回调（auth store 跳转 login），行为与拆分前一致

#### Scenario: index.js 业务方法实现不变

- **WHEN** 调用 `api.getOrders({ stockCode })` / `api.createOrder(orderData)` 等任意业务方法
- **THEN** 方法签名、请求路径、参数处理、返回值与拆分前完全一致
- **AND** 无任何业务逻辑改动，仅 `http` 的导入来源从本文件改为 `./http`

#### Scenario: 文件行数符合 CLAUDE.md 250 行约束

- **WHEN** 拆分完成后检查 `api/http.js` 与 `api/index.js` 行数
- **THEN** 两文件均 < 250 行（http.js ~110，index.js ~220）
- **AND** 单文件职责单一：http.js 只管 HTTP 基础设施，index.js 只管业务 endpoint 聚合
