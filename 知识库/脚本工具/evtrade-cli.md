# EvTrade CLI 工具（`scripts/evtrade_cli/`）

> **用途**：从命令行调 EvTrade 后端 API，做下单/撤单/查持仓/订阅 WS。**替代旧 `evtrade-trading` Hermes skill**。

> 触发场景：AI 助手或用户在 terminal 调 EvTrade :8000 做交易操作（vs `evctl.py` 启停服务）。

---

## 一、3 个脚本

| 脚本 | 功能 |
|---|---|
| `ev_login.py` | 拿 admin JWT, 缓存到 `~/.ev_token.json`。自动用 v118+ seed 账号 `admin / admin123`（`--reset-admin` 可强制重置） |
| `ev_api.py` | HTTP API 封装：buy / sell / cancel / asset / positions / orders / trades / stock |
| `ev_ws.py` | 实时 WS 订阅：subscribe (单股 tick) / watch (多频道 ord_cfm / trd_cfm / asset_update) / replay |

---

## 二、用法

### 1. 拿 token

```bash
python3 scripts/evtrade_cli/ev_login.py --json
# 输出: {"token": "eyJ...", "user_id": 6, "role": "admin", "expires_at": ...}
```

token 自动缓存到 `~/.ev_token.json`，ev_api.py / ev_ws.py 自动读。

### 2. 下单 / 撤单

```bash
# 限价买 600519.SH 100 股 @ 1820.5
python3 scripts/evtrade_cli/ev_api.py buy 600519.SH 100 1820.5

# 撤单
python3 scripts/evtrade_cli/ev_api.py cancel 10000001

# 查持仓 (admin 视角: 全账号)
python3 scripts/evtrade_cli/ev_api.py positions --json

# 查资金
python3 scripts/evtrade_cli/ev_api.py asset
```

### 3. 实时订阅 WS

```bash
# 单股 tick 60s
python3 scripts/evtrade_cli/ev_ws.py subscribe 600519.SH --duration 60

# 多频道: 订阅 ord_cfm + trd_cfm + asset_update 30s
python3 scripts/evtrade_cli/ev_ws.py watch --order --trade --asset --duration 30

# 重连后重放订阅
python3 scripts/evtrade_cli/ev_ws.py replay order_update --limit 10
```

---

## 三、环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `EV_BASE_URL` | `http://127.0.0.1:8000` | 后端 API 地址 |
| `EV_USER` | `admin` | 登录用户名 |
| `EV_PASS` | `admin123` | 登录密码 |

---

## 四、API 端点速查（详见各脚本 argparse --help）

| 类别 | 端点 | 备注 |
|---|---|---|
| 认证 | `POST /api/auth/login` | OAuth2PasswordRequestForm, 返 access_token |
| 认证 | `POST /api/auth/heartbeat` | token 鉴权，触发 session.touch |
| 下单 | `POST /api/orders/stock` | 返 `code=0` 立即 ack；真实状态由 WS ord_cfm 异步推 |
| 撤单 | `DELETE /api/orders/{order_no}` | query: `trd_date=YYYYMMDD` |
| 资金 | `GET /api/asset` | 单行 wide-table (Assets id=1) |
| 持仓 | `GET /api/positions` | v118+ 后 broker pos_push 覆盖 |
| 委托 | `GET /api/orders` | query: `status=pending/filled/cancelled/partial` |
| 成交 | `GET /api/trades` | query: `date=YYYYMMDD` |
| 股票 | `GET /api/stocks/{code}` | 股票基本信息**

---

## 五、WS 频道速查

| 频道 | 用途 | payload |
|---|---|---|
| `order_update` | 订单状态变化 | `{type:'ord_cfm', data:{order_no, status, status_msg, ...}}` |
| `trade_update` | 成交回报 | `{type:'trd_cfm', data:{trade_id, order_no, volume, price, ...}}` |
| `position_update` | 持仓变化 | `{position:{stock_code, last_vol, vol, avl_vol, cost_price}}` |
| `asset_update` | 资金变化 | `{asset:{total_asset, available, frozen, ...}}` |
| `quote_update` | 行情 tick | `{tick:{stock_code, last_price, volume, ...}}` |

详见 `知识库/后端服务/WebSocket推送/`。

---

## 六、关联

- 服务启停用 `scripts/evctl.py`（不是 ev_api.py）
- schema 漂移用 `scripts/sync_schema.py diff`
- 表生成用 `scripts/gen_tables.py`
- 真实业务代码路径见 `知识库/后端服务/交易核心/`