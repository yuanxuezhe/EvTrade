# Cross · 01 · 数据契约（Data Models）

> 跨前后端共享的数据形状。所有契约来源：
> - 后端 dataclass：`server/models/types.py`
> - 后端 Pydantic：`server/api/*.py` 的 `*Response` 模型
> - 前端 Pinia store：`client/src/stores/*.js`
> - 前端组件 props：`client/src/components/*.vue`

## 1. `User`

### 1.1 字段
| 字段 | 类型 | ORM 必填 | 必填于 API | 说明 |
|------|------|----------|------------|------|
| `id` | int | ✅ PK | 仅出参 | 自增 |
| `username` | str(3-32) | ✅ unique | ✅ 创建必填 | 字母/数字/_/-/. |
| `password_hash` | str | ✅ | ❌ | bcrypt 哈希，**不对外暴露** |
| `email` | str(128) | ❌ | ❌ | 可选；空串→null |
| `full_name` | str(64) | ❌ | ❌ | 可选；空串→null |
| `role` | enum | ✅ | ✅ 创建必填 | `admin` / `trader` / `viewer` |
| `is_active` | bool | ✅ | ❌ 创建默认 true | — |
| `created_at` | ISO dt | ✅ | — | UTC |
| `updated_at` | ISO dt | ✅ | — | UTC |
| `last_login_at` | ISO dt | ❌ | — | 登录时更新 |

### 1.2 序列化
`User.to_dict()` 输出（登录 `user` 字段、`/api/auth/me`、用户管理 list/update）：
```json
{
  "id": 1, "username": "admin",
  "email": null, "full_name": "系统管理员",
  "role": "admin", "is_active": true,
  "created_at": "2026-06-09T08:00:00",
  "updated_at": "2026-06-09T08:00:00",
  "last_login_at": "2026-06-09T09:00:00"
}
```

## 2. `TokenResponse`
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 86400,
  "user": { ...User 序列化... }
}
```

## 3. `Position`
| 字段 | 类型 | 来源 | 说明 |
|------|------|------|------|
| `stock_code` | str | 必填 | 如 `000001.SZ` |
| `stock_name` | str | RPC | 股票名 |
| `initial_position` | int | 期初 | 日初初始化时记 |
| `today_buy` | int | 今日累计 | 成交 BUY 累加 |
| `today_sell` | int | 今日累计 | 成交 SELL 累加 |
| `available` | int | 计算 | `initial - today_sell + today_buy`（内存） 或 RPC `avl_amt` |
| `total` | int | 计算 | `initial + today_buy - today_sell` |

> 内存中后端使用 `dataclass Position` + 两个 property；前端 `usePositionStore` 直接拿 `available` / `total` 字段（已计算好的）。

## 4. `Order`
| 字段 | 类型 | 说明 |
|------|------|------|
| `order_id` | str | 8 位 UUID（前端） 或 XtQuant 完整号（RPC） |
| `stock_code` | str | — |
| `direction` | enum | `BUY` / `SELL` |
| `volume` | int | 委托量 |
| `price` | float | 委托价 |
| `price_type` | enum | `LIMIT` / `LATEST` / `FAIR` |
| `status` | str | 12 种前端 key（见 `cross/02_order_status.md`） |
| `traded_volume` | int | 已成交量 |
| `traded_price` | float | 加权平均成交价（RPC 给） / 0（内存） |
| `order_time` | str | `HH:MM:SS` 形式 |

## 5. `Trade`
| 字段 | 类型 | 说明 |
|------|------|------|
| `trade_id` | str | 成交编号 |
| `order_id` | str | 关联委托号 |
| `stock_code` | str | — |
| `direction` | enum | `BUY` / `SELL` |
| `volume` | int | — |
| `price` | float | — |
| `trade_time` | str | `HH:MM:SS` |

## 6. `Asset`
| 字段 | 类型 | 说明 |
|------|------|------|
| `cash` | float | 可用资金 |
| `frozen_cash` | float | 冻结资金 |
| `market_value` | float | 持仓市值 |
| `total_asset` | float | 总资产 = cash + frozen_cash + market_value |

## 7. `OrderCreate`（请求体）
```ts
{
  stock_code: string
  direction:  'BUY' | 'SELL'
  volume:     number  // 整数，≥ 100（前端硬约束）
  price:      number  // 浮点 2 位小数
  price_type: 'LIMIT' | 'LATEST' | 'FAIR'  // 默认 'LIMIT'
}
```

## 8. `ChangePasswordRequest` / `UpdateProfileRequest` / `UserCreateRequest` / `UserUpdateRequest` / `PasswordResetRequest`

| 模型 | 字段 | 校验 |
|------|------|------|
| ChangePasswordRequest | old_password, new_password | new ≥ 6；new ≠ old |
| UpdateProfileRequest | email?, full_name? | 空串→null |
| UserCreateRequest | username, password, role='trader', email?, full_name?, is_active=true | username 正则；password ≥ 6；role ∈ enum |
| UserUpdateRequest | role?, email?, full_name?, is_active? | 同上 + 最后 admin 保护 |
| PasswordResetRequest | new_password | ≥ 6 |

## 9. 错误响应（统一）
```json
{ "detail": "用户不存在" }
```
状态码：400 / 401 / 403 / 404 / 409 / 500

## 10. 时间格式约定

- 服务端 → 客户端：**ISO 8601 字符串**（`User.created_at` / `last_login_at` 等）
- 客户端展示：用 `formatDateTime()` 转 `YYYY-MM-DD HH:mm:ss`
- 委托/成交时间：**`HH:mm:ss` 短串**（非 ISO），按字符串降序排序

## 11. 跨端一致性 checklist

新增字段时必须同步：
- [ ] 后端 dataclass（`models/types.py`）
- [ ] 后端 Pydantic `*Response`（`api/*.py`）
- [ ] 前端 store 字段名 + 类型
- [ ] 前端视图渲染逻辑
- [ ] KB（本文件）
