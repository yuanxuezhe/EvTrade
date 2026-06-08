# Vue交易系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现EvTrade Web交易系统，包含持仓管理、做T操作、交易下单、资金展示功能

**Architecture:** Vue3前端 + FastAPI后端，通过HTTP API和WebSocket通信，后端通过RabbitMQ RPC调用XtQuant交易API

**Tech Stack:** Vue 3 + Pinia + Element Plus / FastAPI + aio-pika + WebSocket

---

## 文件结构

```
D:\workspace\EvTrade\
├── client/ # Vue前端
│   ├── src/
│   │   ├── api/
│   │   │   └── index.js            # HTTP/WebSocket API调用
│   │   ├── stores/
│   │   │   ├── position.js         # 持仓store
│   │   │   ├── order.js            # 委托store
│   │   │   └── asset.js            # 资金store
│   │   ├── views/
│   │   │   ├── Position.vue       # 持仓页面（主页）
│   │   │   ├── Trade.vue          # 交易面板
│   │   │   └── Asset.vue          # 资金页面
│   │   ├── components/
│   │   │   ├── PositionTable.vue   # 持仓列表组件
│   │   │   ├── PositionDetail.vue  # 持仓明细面板
│   │   │   └── OrderForm.vue      # 下单表单组件
│   │   ├── router/
│   │   │   └── index.js
│   │   ├── App.vue
│   │   └── main.js
│   ├── package.json
│   ├── vite.config.js
│   └── index.html
├── server/                         # Python后端
│   ├── main.py                    # FastAPI入口
│   ├── api/
│   │   ├── positions.py           # 持仓API
│   │   ├── orders.py              # 委托API
│   │   ├── trades.py              # 成交API
│   │   └── asset.py                # 资金API
│   ├── ws/
│   │   └── manager.py             # WebSocket连接管理
│   ├── rpc/
│   │   └── client.py              # RabbitMQ RPC客户端
│   ├── models/
│   │   └── types.py               # 数据模型定义
│   └── services/
│       └── trading.py             # 交易服务
├── docs/
│   └── specs/
└── iquant/
    ├── xtquant_api.py
    └── demo_rpc_client.py
```

---

## Task 1: 项目初始化 - 创建目录和配置文件

**Files:**
- Create: `client/package.json`
- Create: `client/vite.config.js`
- Create: `client/index.html`
- Create: `client/src/main.js`
- Create: `client/src/App.vue`
- Create: `server/main.py`
- Create: `server/models/types.py`

- [ ] **Step 1: Create client/package.json**

```json
{
  "name": "evtrade-client",
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "vue": "^3.4.0",
    "vue-router": "^4.2.0",
    "pinia": "^2.1.0",
    "element-plus": "^2.5.0",
    "axios": "^1.6.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.0.0",
    "vite": "^5.0.0"
  }
}
```

Run: `ls D:\workspace\EvTrade\client\`

- [ ] **Step 2: Create client/vite.config.js**

```javascript
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true
      }
    }
  }
})
```

- [ ] **Step 3: Create client/index.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>EvTrade - 交易系统</title>
</head>
<body>
  <div id="app"></div>
  <script type="module" src="/src/main.js"></script>
</body>
</html>
```

- [ ] **Step 4: Create client/src/main.js**

```javascript
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import router from './router'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(ElementPlus)
app.mount('#app')
```

- [ ] **Step 5: Create client/src/App.vue**

```vue
<template>
  <div id="app">
    <router-view />
  </div>
</template>

<script setup>
</script>

<style>
#app {
  font-family: 'Microsoft YaHei', sans-serif;
  padding: 20px;
}
</style>
```

- [ ] **Step 6: Create server/main.py**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api import positions, orders, trades, asset

app = FastAPI(title="EvTrade API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(positions.router, prefix="/api/positions", tags=["positions"])
app.include_router(orders.router, prefix="/api/orders", tags=["orders"])
app.include_router(trades.router, prefix="/api/trades", tags=["trades"])
app.include_router(asset.router, prefix="/api/asset", tags=["asset"])

@app.get("/api/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 7: Create server/models/types.py**

```python
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime

@dataclass
class Position:
    stock_code: str
    stock_name: str = ""
    initial_position: int = 0
    today_buy: int = 0
    today_sell: int = 0

    @property
    def available(self) -> int:
        return self.initial_position - self.today_sell + self.today_buy

    @property
    def total(self) -> int:
        return self.initial_position + self.today_buy - self.today_sell

@dataclass
class Order:
    order_id: str
    stock_code: str
    direction: str  # BUY / SELL
    volume: int
    price: float
    price_type: str = "LIMIT"
    status: str = "pending"  # pending / filled / cancelled / rejected
    traded_volume: int = 0
    traded_price: float = 0.0
    order_time: str = ""

@dataclass
class Trade:
    trade_id: str
    order_id: str
    stock_code: str
    direction: str
    volume: int
    price: float
    trade_time: str = ""

@dataclass
class Asset:
    cash: float = 0.0
    frozen_cash: float = 0.0
    market_value: float = 0.0
    total_asset: float = 0.0
```

- [ ] **Step 8: Commit**

```bash
git add client/package.json client/vite.config.js client/index.html client/src/main.js client/src/App.vue server/main.py server/models/types.py
git commit -m "feat: project scaffold - initial files and data models"
```

---

## Task 2: 后端API实现 - 持仓API

**Files:**
- Create: `server/api/__init__.py`
- Create: `server/api/positions.py`
- Create: `server/services/trading.py`
- Modify: `server/main.py`

- [ ] **Step 1: Create server/api/__init__.py**

```python
```

- [ ] **Step 2: Create server/services/trading.py**

```python
from typing import Dict, List, Optional
from datetime import datetime
from models.types import Position, Order, Trade, Asset

# 内存存储（第一版使用内存，后续迁移到数据库）
positions_store: Dict[str, Position] = {}
orders_store: List[Order] = []
trades_store: List[Trade] = []
asset_store = Asset()

def get_positions() -> List[Position]:
    return list(positions_store.values())

def get_position(stock_code: str) -> Optional[Position]:
    return positions_store.get(stock_code)

def init_position(stock_code: str) -> Position:
    pos = positions_store.get(stock_code)
    if pos:
        pos.initial_position = pos.total
        pos.today_buy = 0
        pos.today_sell = 0
    return pos

def update_position_from_trade(trade: Trade):
    pos = positions_store.get(trade.stock_code)
    if not pos:
        pos = Position(stock_code=trade.stock_code, stock_name="")
        positions_store[trade.stock_code] = pos

    if trade.direction == "BUY":
        pos.today_buy += trade.volume
    else:
        pos.today_sell += trade.volume

def add_order(order: Order):
    orders_store.append(order)

def get_orders(stock_code: Optional[str] = None) -> List[Order]:
    if stock_code:
        return [o for o in orders_store if o.stock_code == stock_code]
    return orders_store

def update_order_status(order_id: str, status: str, traded_volume: int = 0, traded_price: float = 0.0):
    for order in orders_store:
        if order.order_id == order_id:
            order.status = status
            order.traded_volume = traded_volume
            order.traded_price = traded_price
            break

def add_trade(trade: Trade):
    trades_store.append(trade)
    update_position_from_trade(trade)

def get_trades(stock_code: Optional[str] = None) -> List[Trade]:
    if stock_code:
        return [t for t in trades_store if t.stock_code == stock_code]
    return trades_store

def get_asset() -> Asset:
    return asset_store

def update_asset(asset: Asset):
    global asset_store
    asset_store = asset
```

- [ ] **Step 3: Create server/api/positions.py**

```python
from fastapi import APIRouter
from typing import List
from pydantic import BaseModel
from services.trading import get_positions, init_position, get_position

router = APIRouter()

class PositionResponse(BaseModel):
    stock_code: str
    stock_name: str
    initial_position: int
    today_buy: int
    today_sell: int
    available: int
    total: int

@router.get("", response_model=List[PositionResponse])
async def list_positions():
    positions = get_positions()
    return [
        PositionResponse(
            stock_code=p.stock_code,
            stock_name=p.stock_name,
            initial_position=p.initial_position,
            today_buy=p.today_buy,
            today_sell=p.today_sell,
            available=p.available,
            total=p.total
        )
        for p in positions
    ]

@router.post("/{stock_code}/init", response_model=PositionResponse)
async def init_stock_position(stock_code: str):
    pos = init_position(stock_code)
    if not pos:
        return {"error": "position not found"}
    return PositionResponse(
        stock_code=pos.stock_code,
        stock_name=pos.stock_name,
        initial_position=pos.initial_position,
        today_buy=pos.today_buy,
        today_sell=pos.today_sell,
        available=pos.available,
        total=pos.total
    )
```

- [ ] **Step 4: Commit**

```bash
git add server/api/__init__.py server/api/positions.py server/services/trading.py
git commit -m "feat: positions API implementation"
```

---

## Task 3: 后端API实现 - 委托、成交、资金API

**Files:**
- Create: `server/api/orders.py`
- Create: `server/api/trades.py`
- Create: `server/api/asset.py`
- Modify: `server/main.py`

- [ ] **Step 1: Create server/api/orders.py**

```python
from fastapi import APIRouter, HTTPException
from typing import List, Optional
from pydantic import BaseModel
from services.trading import get_orders, add_order, update_order_status
from models.types import Order
import uuid
from datetime import datetime

router = APIRouter()

class OrderCreate(BaseModel):
    stock_code: str
    direction: str
    volume: int
    price: float
    price_type: str = "LIMIT"

class OrderResponse(BaseModel):
    order_id: str
    stock_code: str
    direction: str
    volume: int
    price: float
    price_type: str
    status: str
    traded_volume: int
    traded_price: float
    order_time: str

@router.get("", response_model=List[OrderResponse])
async def list_orders(stock_code: Optional[str] = None):
    orders = get_orders(stock_code)
    return [
        OrderResponse(
            order_id=o.order_id,
            stock_code=o.stock_code,
            direction=o.direction,
            volume=o.volume,
            price=o.price,
            price_type=o.price_type,
            status=o.status,
            traded_volume=o.traded_volume,
            traded_price=o.traded_price,
            order_time=o.order_time
        )
        for o in orders
    ]

@router.post("", response_model=OrderResponse)
async def create_order(order_data: OrderCreate):
    order = Order(
        order_id=str(uuid.uuid4())[:8],
        stock_code=order_data.stock_code,
        direction=order_data.direction,
        volume=order_data.volume,
        price=order_data.price,
        price_type=order_data.price_type,
        status="pending",
        order_time=datetime.now().strftime("%H:%M:%S")
    )
    add_order(order)
    return OrderResponse(
        order_id=order.order_id,
        stock_code=order.stock_code,
        direction=order.direction,
        volume=order.volume,
        price=order.price,
        price_type=order.price_type,
        status=order.status,
        traded_volume=order.traded_volume,
        traded_price=order.traded_price,
        order_time=order.order_time
    )

@router.delete("/{order_id}")
async def cancel_order(order_id: str):
    update_order_status(order_id, "cancelled")
    return {"order_id": order_id, "status": "cancelled"}
```

- [ ] **Step 2: Create server/api/trades.py**

```python
from fastapi import APIRouter
from typing import List, Optional
from pydantic import BaseModel
from services.trading import get_trades

router = APIRouter()

class TradeResponse(BaseModel):
    trade_id: str
    order_id: str
    stock_code: str
    direction: str
    volume: int
    price: float
    trade_time: str

@router.get("", response_model=List[TradeResponse])
async def list_trades(stock_code: Optional[str] = None):
    trades = get_trades(stock_code)
    return [
        TradeResponse(
            trade_id=t.trade_id,
            order_id=t.order_id,
            stock_code=t.stock_code,
            direction=t.direction,
            volume=t.volume,
            price=t.price,
            trade_time=t.trade_time
        )
        for t in trades
    ]
```

- [ ] **Step 3: Create server/api/asset.py**

```python
from fastapi import APIRouter
from pydantic import BaseModel
from services.trading import get_asset

router = APIRouter()

class AssetResponse(BaseModel):
    cash: float
    frozen_cash: float
    market_value: float
    total_asset: float

@router.get("", response_model=AssetResponse)
async def get_account_asset():
    asset = get_asset()
    return AssetResponse(
        cash=asset.cash,
        frozen_cash=asset.frozen_cash,
        market_value=asset.market_value,
        total_asset=asset.total_asset
    )
```

- [ ] **Step 4: Update server/main.py to include all routers**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api import positions, orders, trades, asset

app = FastAPI(title="EvTrade API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(positions.router, prefix="/api/positions", tags=["positions"])
app.include_router(orders.router, prefix="/api/orders", tags=["orders"])
app.include_router(trades.router, prefix="/api/trades", tags=["trades"])
app.include_router(asset.router, prefix="/api/asset", tags=["asset"])

@app.get("/api/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 5: Commit**

```bash
git add server/api/orders.py server/api/trades.py server/api/asset.py server/main.py
git commit -m "feat: orders, trades, asset API implementation"
```

---

## Task 4: WebSocket实现

**Files:**
- Create: `server/ws/manager.py`
- Create: `server/ws/__init__.py`
- Modify: `server/main.py`

- [ ] **Step 1: Create server/ws/manager.py**

```python
from fastapi import WebSocket
from typing import Dict, Set
import json

class WSManager:
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {
            "order_update": set(),
            "trade_update": set(),
            "position_update": set(),
            "asset_update": set(),
        }

    async def connect(self, websocket: WebSocket, channel: str = "order_update"):
        await websocket.accept()
        self.active_connections.setdefault(channel, set()).add(websocket)

    def disconnect(self, websocket: WebSocket, channel: str = "order_update"):
        if channel in self.active_connections:
            self.active_connections[channel].discard(websocket)

    async def broadcast(self, channel: str, message: dict):
        if channel not in self.active_connections:
            return
        dead_connections = set()
        for connection in self.active_connections[channel]:
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.add(connection)
        for conn in dead_connections:
            self.active_connections[channel].discard(conn)

ws_manager = WSManager()
```

- [ ] **Step 2: Create server/ws/__init__.py**

```python
from ws.manager import ws_manager, WSManager

__all__ = ["ws_manager", "WSManager"]
```

- [ ] **Step 3: Update server/main.py with WebSocket endpoint**

```python
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from api import positions, orders, trades, asset
from ws.manager import ws_manager

app = FastAPI(title="EvTrade API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(positions.router, prefix="/api/positions", tags=["positions"])
app.include_router(orders.router, prefix="/api/orders", tags=["orders"])
app.include_router(trades.router, prefix="/api/trades", tags=["trades"])
app.include_router(asset.router, prefix="/api/asset", tags=["asset"])

@app.get("/api/health")
async def health():
    return {"status": "ok"}

@app.websocket("/ws/{channel}")
async def websocket_endpoint(websocket: WebSocket, channel: str):
    await ws_manager.connect(websocket, channel)
    try:
        while True:
            data = await websocket.receive_text()
            # handle client messages if needed
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, channel)
```

- [ ] **Step 4: Commit**

```bash
git add server/ws/manager.py server/ws/__init__.py server/main.py
git commit -m "feat: WebSocket implementation"
```

---

## Task 5: 前端API层实现

**Files:**
- Create: `client/src/api/index.js`
- Create: `client/src/router/index.js`

- [ ] **Step 1: Create client/src/api/index.js**

```javascript
import axios from 'axios'
import { ref } from 'vue'

const API_BASE = '/api'

// HTTP API
export const api = {
  // 持仓
  async getPositions() {
    const res = await axios.get(`${API_BASE}/positions`)
    return res.data
  },
  async initPosition(stockCode) {
    const res = await axios.post(`${API_BASE}/positions/${stockCode}/init`)
    return res.data
  },

  // 委托
  async getOrders(stockCode) {
    const params = stockCode ? { stock_code: stockCode } : {}
    const res = await axios.get(`${API_BASE}/orders`, { params })
    return res.data
  },
  async createOrder(orderData) {
    const res = await axios.post(`${API_BASE}/orders`, orderData)
    return res.data
  },
  async cancelOrder(orderId) {
    const res = await axios.delete(`${API_BASE}/orders/${orderId}`)
    return res.data
  },

  // 成交
  async getTrades(stockCode) {
    const params = stockCode ? { stock_code: stockCode } : {}
    const res = await axios.get(`${API_BASE}/trades`, { params })
    return res.data
  },

  // 资金
  async getAsset() {
    const res = await axios.get(`${API_BASE}/asset`)
    return res.data
  }
}

// WebSocket
export function createWSConnection(channel = 'order_update') {
  const wsUrl = `ws://${window.location.host}/ws/${channel}`
  const ws = ref(null)
  const messages = ref([])
  const connected = ref(false)

  function connect() {
    ws.value = new WebSocket(wsUrl)

    ws.value.onopen = () => {
      connected.value = true
      console.log(`[WS] Connected to ${channel}`)
    }

    ws.value.onmessage = (event) => {
      const data = JSON.parse(event.data)
      messages.value.push(data)
    }

    ws.value.onclose = () => {
      connected.value = false
      console.log(`[WS] Disconnected from ${channel}`)
    }

    ws.value.onerror = (error) => {
      console.error(`[WS] Error on ${channel}:`, error)
    }
  }

  function disconnect() {
    if (ws.value) {
      ws.value.close()
    }
  }

  connect()

  return {
    ws,
    messages,
    connected,
    disconnect
  }
}
```

- [ ] **Step 2: Create client/src/router/index.js**

```javascript
import { createRouter, createWebHistory } from 'vue-router'
import Position from '../views/Position.vue'
import Trade from '../views/Trade.vue'
import Asset from '../views/Asset.vue'

const routes = [
  { path: '/', name: 'Position', component: Position },
  { path: '/trade', name: 'Trade', component: Trade },
  { path: '/asset', name: 'Asset', component: Asset }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
```

- [ ] **Step 3: Commit**

```bash
git add client/src/api/index.js client/src/router/index.js
git commit -m "feat: frontend API layer and router"
```

---

## Task 6: 前端Pinia Stores

**Files:**
- Create: `client/src/stores/position.js`
- Create: `client/src/stores/order.js`
- Create: `client/src/stores/asset.js`

- [ ] **Step 1: Create client/src/stores/position.js**

```javascript
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '../api'

export const usePositionStore = defineStore('position', () => {
  const positions = ref([])
  const selectedStockCode = ref(null)

  const selectedPosition = computed(() => {
    if (!selectedStockCode.value) return null
    return positions.value.find(p => p.stock_code === selectedStockCode.value)
  })

  async function fetchPositions() {
    positions.value = await api.getPositions()
  }

  async function initPosition(stockCode) {
    await api.initPosition(stockCode)
    await fetchPositions()
  }

  function selectStock(stockCode) {
    selectedStockCode.value = stockCode
  }

  return {
    positions,
    selectedStockCode,
    selectedPosition,
    fetchPositions,
    initPosition,
    selectStock
  }
})
```

- [ ] **Step 2: Create client/src/stores/order.js**

```javascript
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api'

export const useOrderStore = defineStore('order', () => {
  const orders = ref([])
  const trades = ref([])

  async function fetchOrders(stockCode) {
    orders.value = await api.getOrders(stockCode)
  }

  async function fetchTrades(stockCode) {
    trades.value = await api.getTrades(stockCode)
  }

  async function createOrder(orderData) {
    const order = await api.createOrder(orderData)
    orders.value.push(order)
    return order
  }

  async function cancelOrder(orderId) {
    await api.cancelOrder(orderId)
    const order = orders.value.find(o => o.order_id === orderId)
    if (order) {
      order.status = 'cancelled'
    }
  }

  return {
    orders,
    trades,
    fetchOrders,
    fetchTrades,
    createOrder,
    cancelOrder
  }
})
```

- [ ] **Step 3: Create client/src/stores/asset.js**

```javascript
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api'

export const useAssetStore = defineStore('asset', () => {
  const asset = ref({
    cash: 0,
    frozen_cash: 0,
    market_value: 0,
    total_asset: 0
  })

  async function fetchAsset() {
    asset.value = await api.getAsset()
  }

  return {
    asset,
    fetchAsset
  }
})
```

- [ ] **Step 4: Commit**

```bash
git add client/src/stores/position.js client/src/stores/order.js client/src/stores/asset.js
git commit -m "feat: frontend Pinia stores"
```

---

## Task 7: 前端组件 - PositionTable

**Files:**
- Create: `client/src/components/PositionTable.vue`

- [ ] **Step 1: Create client/src/components/PositionTable.vue**

```vue
<template>
  <el-table :data="positions" highlight-current-row @row-click="handleRowClick" style="width: 100%">
    <el-table-column prop="stock_code" label="股票代码" width="120" />
    <el-table-column prop="stock_name" label="股票名称" width="120" />
    <el-table-column prop="initial_position" label="期初" width="100" align="right" />
    <el-table-column prop="today_buy" label="买入" width="100" align="right" />
    <el-table-column prop="today_sell" label="卖出" width="100" align="right" />
    <el-table-column prop="available" label="可用" width="100" align="right" />
    <el-table-column prop="total" label="总持仓" width="100" align="right" />
  </el-table>
</template>

<script setup>
const props = defineProps({
  positions: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['select'])

function handleRowClick(row) {
  emit('select', row.stock_code)
}
</script>
```

- [ ] **Step 2: Commit**

```bash
git add client/src/components/PositionTable.vue
git commit -m "feat: PositionTable component"
```

---

## Task 8: 前端组件 - PositionDetail

**Files:**
- Create: `client/src/components/PositionDetail.vue`

- [ ] **Step 1: Create client/src/components/PositionDetail.vue**

```vue
<template>
  <div class="position-detail">
    <div class="detail-header">
      <h3>{{ stockCode }} 委托/成交明细</h3>
    </div>

    <el-table :data="orderTradeList" style="width: 100%" size="small">
      <el-table-column prop="time" label="时间" width="100" />
      <el-table-column prop="type" label="类型" width="60">
        <template #default="{ row }">
          <el-tag :type="row.type === '委托' ? 'info' : 'success'" size="small">
            {{ row.type }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="direction" label="方向" width="60">
        <template #default="{ row }">
          <span :class="row.direction === 'BUY' ? 'text-buy' : 'text-sell'">
            {{ row.direction === 'BUY' ? '买入' : '卖出' }}
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="volume" label="数量" width="100" align="right" />
      <el-table-column prop="price" label="价格" width="100" align="right">
        <template #default="{ row }">
          {{ row.price.toFixed(2) }}
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="80" />
      <el-table-column prop="order_id" label="委托号" />
    </el-table>

    <div class="summary">
      <div class="profit">
        做T收益: <span :class="profit >= 0 ? 'text-buy' : 'text-sell'">¥{{ profit.toFixed(2) }}</span>
      </div>
      <div class="rebalance">
        需买回: <span class="text-sell">{{ needBuyBack }}股</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  orders: { type: Array, default: () => [] },
  trades: { type: Array, default: () => [] },
  position: { type: Object, default: null },
  stockCode: { type: String, default: '' }
})

const orderTradeList = computed(() => {
  const list = []

  for (const order of props.orders) {
    list.push({
      time: order.order_time,
      type: '委托',
      direction: order.direction,
      volume: order.volume,
      price: order.price,
      status: order.status === 'filled' ? '成交' : order.status,
      order_id: order.order_id
    })
  }

  for (const trade of props.trades) {
    list.push({
      time: trade.trade_time,
      type: '成交',
      direction: trade.direction,
      volume: trade.volume,
      price: trade.price,
      status: '-',
      order_id: trade.order_id
    })
  }

  return list.sort((a, b) => a.time.localeCompare(b.time))
})

const profit = computed(() => {
  if (!props.position) return 0
  const { today_buy, today_sell } = props.position
  const buyVolume = Math.min(today_buy, today_sell)

  const totalBuy = props.trades
    .filter(t => t.direction === 'BUY')
    .reduce((sum, t) => sum + t.volume * t.price, 0)
  const totalSell = props.trades
    .filter(t => t.direction === 'SELL')
    .reduce((sum, t) => sum + t.volume * t.price, 0)

  const avgBuy = today_buy > 0 ? totalBuy / today_buy : 0
  const avgSell = today_sell > 0 ? totalSell / today_sell : 0

  return (avgSell - avgBuy) * buyVolume
})

const needBuyBack = computed(() => {
  if (!props.position) return 0
  const { initial_position, total } = props.position
  return initial_position - total
})
</script>

<style scoped>
.position-detail {
  margin-top: 20px;
  padding: 15px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
}
.detail-header h3 {
  margin: 0 0 15px 0;
}
.summary {
  margin-top: 15px;
  display: flex;
  gap: 30px;
  font-size: 16px;
}
.text-buy { color: #f56c6c; }
.text-sell { color: #67c23a; }
</style>
```

- [ ] **Step 2: Commit**

```bash
git add client/src/components/PositionDetail.vue
git commit -m "feat: PositionDetail component with profit calculation"
```

---

## Task 9: 前端组件 - OrderForm

**Files:**
- Create: `client/src/components/OrderForm.vue`

- [ ] **Step 1: Create client/src/components/OrderForm.vue**

```vue
<template>
  <el-card class="order-form">
    <template #header>
      <span>交易下单</span>
    </template>

    <el-form :model="form" label-width="80px">
      <el-form-item label="股票代码">
        <el-input v-model="form.stock_code" placeholder="如 000001.SZ" />
      </el-form-item>

      <el-form-item label="方向">
        <el-radio-group v-model="form.direction">
          <el-radio label="BUY">买入</el-radio>
          <el-radio label="SELL">卖出</el-radio>
        </el-radio-group>
      </el-form-item>

      <el-form-item label="价格类型">
        <el-select v-model="form.price_type" placeholder="选择价格类型">
          <el-option label="限价" value="LIMIT" />
          <el-option label="最新价" value="LATEST" />
          <el-option label="挂单价" value="FAIR" />
        </el-select>
      </el-form-item>

      <el-form-item label="价格">
        <el-input-number v-model="form.price" :min="0" :precision="2" />
      </el-form-item>

      <el-form-item label="数量">
        <el-input-number v-model="form.volume" :min="100" :step="100" />
      </el-form-item>

      <el-form-item>
        <el-button type="primary" @click="handleSubmit">下单</el-button>
        <el-button @click="handleReset">重置</el-button>
      </el-form-item>
    </el-form>
  </el-card>
</template>

<script setup>
import { reactive } from 'vue'
import { ElMessage } from 'element-plus'

const props = defineProps({
  onSubmit: { type: Function, required: true }
})

const form = reactive({
  stock_code: '',
  direction: 'BUY',
  price_type: 'LIMIT',
  price: 0,
  volume: 100
})

function handleSubmit() {
  if (!form.stock_code) {
    ElMessage.warning('请输入股票代码')
    return
  }
  if (form.price <= 0) {
    ElMessage.warning('请输入价格')
    return
  }
  if (form.volume <= 0) {
    ElMessage.warning('请输入数量')
    return
  }
  props.onSubmit({ ...form })
  handleReset()
}

function handleReset() {
  form.stock_code = ''
  form.direction = 'BUY'
  form.price_type = 'LIMIT'
  form.price = 0
  form.volume = 100
}
</script>

<style scoped>
.order-form {
  max-width: 400px;
}
</style>
```

- [ ] **Step 2: Commit**

```bash
git add client/src/components/OrderForm.vue
git commit -m "feat: OrderForm component"
```

---

## Task 10: 前端页面 - Position.vue

**Files:**
- Create: `client/src/views/Position.vue`

- [ ] **Step 1: Create client/src/views/Position.vue**

```vue
<template>
  <div class="position-page">
    <div class="header">
      <h2>持仓管理</h2>
      <el-button type="warning" @click="handleInit">日初初始化</el-button>
    </div>

    <PositionTable :positions="positionStore.positions" @select="handleSelect" />

    <PositionDetail
      v-if="positionStore.selectedStockCode"
      :stock-code="positionStore.selectedStockCode"
      :position="positionStore.selectedPosition"
      :orders="orderStore.orders"
      :trades="orderStore.trades"
    />
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { usePositionStore } from '../stores/position'
import { useOrderStore } from '../stores/order'
import { ElMessage, ElMessageBox } from 'element-plus'
import PositionTable from '../components/PositionTable.vue'
import PositionDetail from '../components/PositionDetail.vue'

const positionStore = usePositionStore()
const orderStore = useOrderStore()

onMounted(async () => {
  await positionStore.fetchPositions()
})

function handleSelect(stockCode) {
  positionStore.selectStock(stockCode)
  orderStore.fetchOrders(stockCode)
  orderStore.fetchTrades(stockCode)
}

async function handleInit() {
  try {
    await ElMessageBox.confirm(
      '确认进行日初初始化？将重置所有标的的今日买卖数据。',
      '日初初始化',
      { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' }
    )
    for (const pos of positionStore.positions) {
      await positionStore.initPosition(pos.stock_code)
    }
    ElMessage.success('日初初始化完成')
  } catch {
    // cancelled
  }
}
</script>

<style scoped>
.position-page {
  max-width: 1200px;
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.header h2 {
  margin: 0;
}
</style>
```

- [ ] **Step 2: Commit**

```bash
git add client/src/views/Position.vue
git commit -m "feat: Position page view"
```

---

## Task 11: 前端页面 - Trade.vue

**Files:**
- Create: `client/src/views/Trade.vue`

- [ ] **Step 1: Create client/src/views/Trade.vue**

```vue
<template>
  <div class="trade-page">
    <h2>交易面板</h2>

    <div class="trade-content">
      <OrderForm :on-submit="handleOrderSubmit" />

      <div class="order-list">
        <h3>今日委托</h3>
        <el-table :data="orderStore.orders" style="width: 100%">
          <el-table-column prop="order_time" label="时间" width="100" />
          <el-table-column prop="stock_code" label="股票" width="120" />
          <el-table-column prop="direction" label="方向" width="60">
            <template #default="{ row }">
              <span :class="row.direction === 'BUY' ? 'text-buy' : 'text-sell'">
                {{ row.direction === 'BUY' ? '买入' : '卖出' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="volume" label="数量" width="100" align="right" />
          <el-table-column prop="price" label="价格" width="100" align="right">
            <template #default="{ row }">
              {{ row.price.toFixed(2) }}
            </template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="80">
            <template #default="{ row }">
              <el-tag :type="getStatusType(row.status)" size="small">
                {{ row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="80">
            <template #default="{ row }">
              <el-button
                v-if="row.status === 'pending'"
                type="danger"
                size="small"
                @click="handleCancel(row.order_id)"
              >
                撤单
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useOrderStore } from '../stores/order'
import { ElMessage } from 'element-plus'
import OrderForm from '../components/OrderForm.vue'

const orderStore = useOrderStore()

onMounted(async () => {
  await orderStore.fetchOrders()
})

async function handleOrderSubmit(orderData) {
  try {
    await orderStore.createOrder(orderData)
    ElMessage.success('下单成功')
  } catch (error) {
    ElMessage.error('下单失败')
  }
}

async function handleCancel(orderId) {
  try {
    await orderStore.cancelOrder(orderId)
    ElMessage.success('撤单成功')
  } catch (error) {
    ElMessage.error('撤单失败')
  }
}

function getStatusType(status) {
  const map = {
    pending: 'warning',
    filled: 'success',
    cancelled: 'info',
    rejected: 'danger'
  }
  return map[status] || 'info'
}
</script>

<style scoped>
.trade-page {
  max-width: 1000px;
}
.trade-content {
  display: flex;
  gap: 20px;
}
.order-list {
  flex: 1;
}
.text-buy { color: #f56c6c; }
.text-sell { color: #67c23a; }
</style>
```

- [ ] **Step 2: Commit**

```bash
git add client/src/views/Trade.vue
git commit -m "feat: Trade page view"
```

---

## Task 12: 前端页面 - Asset.vue

**Files:**
- Create: `client/src/views/Asset.vue`

- [ ] **Step 1: Create client/src/views/Asset.vue**

```vue
<template>
  <div class="asset-page">
    <h2>账户资金</h2>

    <el-card class="asset-card">
      <el-descriptions :column="2" border>
        <el-descriptions-item label="可用资金">
          <span class="asset-value">¥{{ assetStore.asset.cash.toFixed(2) }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="冻结资金">
          <span class="asset-value">¥{{ assetStore.asset.frozen_cash.toFixed(2) }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="持仓市值">
          <span class="asset-value">¥{{ assetStore.asset.market_value.toFixed(2) }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="总资产">
          <span class="asset-value total">¥{{ assetStore.asset.total_asset.toFixed(2) }}</span>
        </el-descriptions-item>
      </el-descriptions>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useAssetStore } from '../stores/asset'

const assetStore = useAssetStore()

onMounted(async () => {
  await assetStore.fetchAsset()
})
</script>

<style scoped>
.asset-page {
  max-width: 800px;
}
.asset-value {
  font-size: 18px;
  font-weight: 500;
}
.asset-value.total {
  color: #409eff;
  font-size: 22px;
}
</style>
```

- [ ] **Step 2: Commit**

```bash
git add client/src/views/Asset.vue
git commit -m "feat: Asset page view"
```

---

## Task 13: 添加导航和布局

**Files:**
- Modify: `client/src/App.vue`
- Create: `client/src/components/NavBar.vue`

- [ ] **Step 1: Create client/src/components/NavBar.vue**

```vue
<template>
  <el-menu mode="horizontal" :router="true">
    <el-menu-item index="/">持仓管理</el-menu-item>
    <el-menu-item index="/trade">交易面板</el-menu-item>
    <el-menu-item index="/asset">资金</el-menu-item>
  </el-menu>
</template>
```

- [ ] **Step 2: Update client/src/App.vue**

```vue
<template>
  <div id="app">
    <NavBar />
    <router-view style="margin-top: 20px" />
  </div>
</template>

<script setup>
import NavBar from './components/NavBar.vue'
</script>

<style>
#app {
  font-family: 'Microsoft YaHei', sans-serif;
}
</style>
```

- [ ] **Step 3: Commit**

```bash
git add client/src/components/NavBar.vue client/src/App.vue
git commit -m "feat: add navigation bar and layout"
```

---

## 实施选择

**Plan complete and saved to `docs/superpowers/plans/2026-06-08-vue-trading-system-implementation-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**