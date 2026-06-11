# EvTrade P0 Sprint 规格说明

> 创建时间：2026-06-11
> 基线 commit：待 `git rev-parse HEAD` 时记录
> 关联文档：`PROJECT_ANALYSIS_REPORT.md`（已过时，本文档为准）
> 编码规范：`/root/workspcae/codespace/CLAUDE.md`

---

## 0. 校准说明

子代理早期生成的 `PROJECT_ANALYSIS_REPORT.md` 标记为「🔴 高优先级」的
WS 路由挂载 / Push 队列消费者 / `get_asset` 走本地三件事
**已经在当前代码中实现**。本 Sprint 只针对**真实剩余的 P0 问题**。

| 报告里的"未实现" | 当前真实状态 | 证据 |
|---|---|---|
| WS 路由未挂载 | ✅ 已实现 | `server/main.py:87-99` |
| Push 消费者未实现 | ✅ 已实现 | `server/rpc/client.py:125-183` |
| `get_asset` 走本地 SDK | ✅ 已切回 RPC | `server/api/asset.py` |

---

## 1. P0 问题清单（重新校准后）

### P0-1 🔴 撤单无法工作

**位置**：`server/rpc/client.py:567-571`

```python
async def cancel_order(order_id: str) -> Dict[str, Any]:
    """撤单 cancel_ord（占位实现，未把 order_id 写入请求体）"""
    client = await get_rpc_client()
    pkt = await client.call("cancel_ord")
    return _parse_order_ack(pkt)
```

**问题**：
- 注释明确说明「未把 order_id 写入请求体」
- 调用方在 `orders.py:193-196` 会传 `order_id`，但 RPC 客户端**丢弃了**
- 后果：撤单请求 100% 会被柜台拒绝（缺 order_id）

**修复**：
1. 仿照 `ord_stk` 的实现，把 `order_id` 作为请求体字段
2. 需要确认柜台 `cancel_ord` 协议的字段名（参考 `ord_stk` 头表 `stock_code,volume,...`）
3. 加单元测试：mock 柜台应答，验证请求包中 `order_id` 存在

**验收**：
- `pytest server/tests/test_rpc_client.py::test_cancel_order_sends_order_id` 通过
- 手动：`curl -X DELETE http://localhost:8002/api/orders/<id> -H "Authorization: Bearer <token>"` 返回 `code=0`

---

### P0-2 🔴 `create_order` 走内存而不是 RPC

**位置**：`server/api/orders.py:143-169` vs `orders.py:172-190`

```python
# 143 行：POST /api/orders  走 in-memory
@router.post("", response_model=OrderResponse)
async def create_order(order_data: OrderCreate, _=Depends(require_trader)):
    order = Order(order_id=str(uuid.uuid4())[:8], ..., status="pending", ...)
    add_order(order)   # ← 只写内存
    return OrderResponse(...)

# 172 行：POST /api/orders/place  走 RPC
@router.post("/place", response_model=OrderAckRpcResponse)
async def place_order(order_data: OrderCreate, _=Depends(require_trader)):
    result = await ord_stk(...)
```

**问题**：
- 两个 POST 端点共存，前端 `api/index.js` 用哪个？报告说前端调 `/api/orders` POST
- 如果调的是 `""`（不带 `/place`）—— 订单**只进内存，柜台完全没有委托**
- 前端用户看不到真实委托、撤不了单、看不到成交

**修复**（二选一，推荐 A）：

**方案 A（推荐）**：让 `POST /api/orders` 直接走 RPC，删除 `POST /api/orders/place`：
- 行为与报告 §八描述一致
- 风险：现有前端若有调用 `/place` 的代码需同步改
- 步骤：
  1. 合并两个端点，`POST /api/orders` 内部先写内存（拿临时 ID），再 `await ord_stk()`，用柜台返回的 order_id 替换
  2. 加事务：RPC 失败回滚内存
  3. 同步检查并修改前端 `client/src/api/index.js` 中所有 POST /api/orders 调用

**方案 B（保守）**：保留双端点，但 `POST /api/orders` 内部转发到 `ord_stk`：
- 不动前端
- 风险：临时 order_id 与柜台 order_id 不一致问题依旧

**验收**：
- 方案 A：`POST /api/orders` 返回 `OrderResponse.order_id` 是柜台回单号（数字串，不是 UUID 前 8 位）
- 单元测试：mock `ord_stk` 返回 `{code:0, msg:"", list:[{"order_id":"QMT12345"}]}`，验证响应 `order_id == "QMT12345"`

---

### P0-3 🟡 `services/xtquant.py` 是死代码

**位置**：`server/services/xtquant.py`（76 行）

```python
sys.path.insert(0, r'D:\software\trade\iQuant')   # Windows 硬路径
sys.path.insert(0, r'D:\software\trade\iQuant\Lib\site-packages')
TRADE_PATH = r'D:\software\trade\iQuant\userdata'  # Windows 硬路径
ACCOUNT_ID = '410001265100'                         # 硬编码账户
```

**问题**：
- `grep -r "from services.xtquant" server/` 应该无结果（若 `api/asset.py` 已切回 RPC）
- 死代码 + 硬编码 + Windows-only 路径，对 Linux 部署是定时炸弹
- 即便 `services/trading.py` 还 import 了 `set_trader`，但已无调用方

**修复**：
1. `git grep -n "from services.xtquant\|services\\.xtquant" server/ client/` 确认无引用
2. `git rm server/services/xtquant.py`
3. 同步清理 `services/trading.py` 中的 `set_trader / get_trader / get_account`（若仅 xtquant 用）
4. 若确有本地 XtQuant 需求（如开发环境断网调试），保留但加：
   - 顶部 `import platform` + 守卫：`if platform.system() != "Windows": return None`
   - 配置项从 `EVTRADE_TRADE_PATH` / `EVTRADE_ACCOUNT_ID` 读，不写死
   - 加 `EVTRADE_USE_LOCAL_XTQUANT` 开关（默认 `False`）

**验收**：
- `git grep "xtquant"` 在 `server/services/xtquant.py` 之外**无业务引用**
- 单元测试：在 Linux 下 `import server.main` 不报 `ModuleNotFoundError: xtquant`

---

### P0-4 🟡 前端 WS 仅 Dashboard 占位

**位置**：
- 后端：`server/ws/manager.py`（已实现）
- 前端：`client/src/stores/ws.js`（9.5KB，已实现）+ `client/src/views/Dashboard.vue`（占位调用）

**问题**：
- Trade.vue / Orders.vue / Position.vue / Asset.vue 仍是 5s `setInterval` 轮询
- 真实回报已通过 `rpc/client.py:125` 的 `_listen_pushs()` 推到 `ws_manager.broadcast()`
- 频道：`order_update / trade_update / position_update / asset_update`
- 但前端除 Dashboard 外**不订阅** → 推送白做

**修复**（最小改动）：
1. **Trade.vue**：下单成功后 `ws.subscribe('order_update')`，收到推送时立即 `fetchOrders()`（跳过下次轮询），停止 `setInterval`
2. **Orders.vue**：进入页面 `ws.subscribe('order_update')` + `ws.subscribe('trade_update')`；离开页面 `unsubscribe` + 停轮询
3. **Position.vue**：`ws.subscribe('position_update')`；触发时 `fetchPositions()`
4. **Asset.vue**：`ws.subscribe('asset_update')`；触发时 `fetchAsset()`
5. 加 `document.visibilitychange` 监听：页面隐藏时停轮询、关闭 WS；可见时恢复
6. 加去重：WS 推送 < 轮询间隔（如 < 2s）则跳过下次轮询

**验收**：
- 手动测试：Trade.vue 下单后 < 200ms 看到委托列表出现新单（vs 之前最多 5s 延迟）
- `git grep -n "setInterval" client/src/views/` 应该只余 Dashboard 与定时刷新（如无则全部清掉）

---

### P0-5 🟢 价格类型集中枚举

**位置**：
- `server/api/orders.py:20` `price_type: int = 11`
- `client/src/components/OrderForm.vue`（推测有 `11/5/14/44` 数字）
- `server/rpc/client.py:546` 注释

**问题**：
- 数字常量（11/5/14/44）散落多处，前端硬编码
- 改一处忘改另一处的 bug 高发区

**修复**：
1. 新建 `server/constants.py`：
   ```python
   class PriceType:
       LATEST = 5
       LIMIT = 11
       OPPONENT = 14
       MARKET = 44
       _LABEL = {5: "最新价", 11: "限价", 14: "对手价", 44: "市价"}
       @classmethod
       def label(cls, n: int) -> str: ...
   class OrderType:
       BUY = "23"
       SELL = "24"
   ```
2. 后端 `orders.py` / `rpc/client.py` 全部用 `PriceType.LIMIT`，禁止裸数字
3. 前端 `client/src/constants/priceType.js` 镜像导出
4. `OrderForm.vue` 改用常量引用
5. 加 `pre-commit` 检查：`grep -rn "\\b\\(11\\|5\\|14\\|44\\)\\b" server/api/ server/rpc/ server/services/ | grep -v test_` 应该空

**验收**：
- `git grep -n "price_type.*=.*11" server/` 应该无业务硬编码（仅 `constants.py`）
- 前端表单切换价格类型时仍能正常下单

---

### P0-6 🟢 清理误提交文件

**位置**：
- `server/2.0`（2.7KB，pip install 日志）
- `server/auth/__init__.py`（0 字节空文件）

**修复**：
1. `git rm server/2.0`
2. 在根 `.gitignore` 加 `server/2.0`（防 reappear）+ `*.log`（防未来误提交）
3. `server/auth/__init__.py`：若确实需要（`from server.auth import deps` 才不会触发 implicit namespace），保留空文件但加注释 `"""auth namespace: security, deps."""`；若不需要则 `git rm` 改用 `from auth import deps` 直接导入

**验收**：
- `git log --all -- server/2.0` 显示一次 `delete` 提交
- `cat .gitignore` 含 `server/2.0` 和 `*.log`

---

## 2. Sprint 范围与顺序

| # | 任务 | 估时 | 阻塞关系 |
|---|---|---|---|
| 1 | P0-1 撤单修复 | 30min | — |
| 2 | P0-2 下单端点合并 | 1h | 依赖 1 的 RPC 测试套件 |
| 3 | P0-3 死代码清理 | 15min | — |
| 4 | P0-4 前端 WS 接入 | 2h | 依赖 2（保证下单走 RPC） |
| 5 | P0-5 价格类型枚举 | 30min | — |
| 6 | P0-6 误提交清理 | 10min | — |

**建议执行顺序**：1 → 2 → 5 → 3 → 6 → 4（每完成一个跑测试再进下一个）

---

## 3. 测试计划

### 3.1 后端 pytest

新建 `server/tests/test_rpc_client.py`：

```python
import pytest
from unittest.mock import AsyncMock, patch
from rpc.client import ord_stk, cancel_order, qry_orders

@pytest.mark.asyncio
async def test_ord_stk_sends_all_fields():
    """P0-2 验证：下单请求包含全部 6 个字段"""
    with patch("rpc.client.get_rpc_client") as mock:
        client = AsyncMock()
        client.call = AsyncMock(return_value=mock_ack_packet())
        mock.return_value = client
        await ord_stk("600030.SH", 100, 11, 10.5, "23", remark="test")
        # 解析 publish 入参
        call_args = client.call.call_args
        assert call_args[0][0] == "ord_stk"
        values = call_args[1]["values"]
        assert values["stock_code"] == "600030.SH"
        assert values["volume"] == "100"
        # ... 其他 4 个字段

@pytest.mark.asyncio
async def test_cancel_order_sends_order_id():
    """P0-1 验证：撤单请求包含 order_id"""
    with patch("rpc.client.get_rpc_client") as mock:
        client = AsyncMock()
        client.call = AsyncMock(return_value=mock_ack_packet())
        mock.return_value = client
        await cancel_order("QMT12345")
        call_args = client.call.call_args
        assert call_args[1]["values"]["order_id"] == "QMT12345"
```

新建 `server/tests/test_ws_broadcast.py`：

```python
import pytest
from ws.manager import WSManager
from starlette.websockets import WebSocketState

@pytest.mark.asyncio
async def test_broadcast_to_channel():
    """P0-4 验证：broadcast 把消息投到正确频道"""
    mgr = WSManager()
    ws = AsyncMock(spec=WebSocket)
    await mgr.connect(ws, "order_update")
    await mgr.broadcast("order_update", {"type": "ord_cfm", "data": {"order_id": "1"}})
    ws.send_json.assert_called_once()
    # 不订阅的频道不应收到
    await mgr.broadcast("trade_update", {"type": "trd_cfm"})
    ws.send_json.assert_called_once()  # 仍只 1 次
```

### 3.2 前端 vitest

新建 `client/src/stores/__tests__/ws.spec.js`：

```javascript
import { setActivePinia, createPinia } from 'pinia'
import { useWsStore } from '@/stores/ws'

describe('ws store', () => {
  it('subscribes to channel and stores handler', () => {
    const ws = useWsStore()
    const handler = vi.fn()
    ws.subscribe('order_update', handler)
    expect(ws.channels['order_update']).toContain(handler)
  })

  it('reconnects with exponential backoff', async () => {
    // 模拟 WebSocket 断开，验证重连延迟 1s, 2s, 4s, 8s
  })
})
```

### 3.3 验收脚本

`scripts/verify_p0.sh`（新建）：
```bash
#!/bin/bash
set -e
echo "=== 1. 启动后端 ==="
./scripts/dev.sh start
sleep 3
echo "=== 2. 登录 ==="
TOKEN=$(curl -s -X POST http://localhost:8002/api/auth/login \
  -d "username=admin&password=admin123" | jq -r .access_token)
echo "TOKEN=${TOKEN:0:20}..."
echo "=== 3. 健康检查 ==="
curl -s http://localhost:8002/api/health
echo "=== 4. 撤单端点存在 ==="
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:8002/api/orders/test123
echo "=== 5. WS 端点存在 ==="
# 用 websocat 测试
echo "GET /ws/order_update HTTP/1.1\nHost: localhost:8002\nUpgrade: websocket\n" | \
  nc -w1 localhost 8002 | head -1
echo "=== Done ==="
```

---

## 4. 完成定义（DoD）

- [ ] 所有 6 个 P0 任务 commit（每个独立 commit）
- [ ] `pytest server/tests/` 100% 通过
- [ ] `npm run test` 100% 通过
- [ ] `./scripts/verify_p0.sh` 全部 OK
- [ ] 后端 `git grep "xtquant" server/api/ server/rpc/` 无业务引用
- [ ] 前端 `git grep "setInterval" client/src/views/Trade.vue client/src/views/Orders.vue` 无残留
- [ ] `git log --oneline -10` 显示 6 个独立 feat/fix commit
- [ ] 更新 `PROJECT_ANALYSIS_REPORT.md` 的完成度表格（11.2 节）

---

## 5. 风险与回滚

| 风险 | 缓解 |
|---|---|
| 撤单修复时猜错柜台字段名 | 先读 `kb/cross/02_order_status.md` 和 `iquant/demo_rpc_client.py` 确认 |
| 下单端点合并影响前端 | 先 `git grep "api/orders" client/src/` 列全调用点 |
| 前端 WS 接入有竞态（WS 未连上就下单） | 在 `ws.js` 加 `await ws.ready` Promise，下单前 await |
| 价格类型枚举改后单元测试不通过 | 测试用 `PriceType.LIMIT` 别用数字 |
| Linux 部署 `services/xtquant.py` 删除后断本地 dev | 加 `EVTRADE_USE_LOCAL_XTQUANT=true` 开关默认 false |

---

## 6. 后续 Sprint（不在本 Sprint 范围）

- P1: token 黑名单（Redis 或 DB）、`visibilitychange` 轮询暂停、统一错误处理 toast
- P1: 硬编码配置全部抽到 `EVTRADE_*` 环境变量
- P1: `.env.sc` 审计 + 移除
- P1: KB 文档与代码对账（`ls kb/` vs `kb/README.md` 索引）
- P2: ECharts 按需引入、components/views 命名统一
- P2: 测试覆盖率报告（pytest-cov / vitest --coverage）
