# Cross · 04 · iQuant 集成与协议参考

> 目录：`iquant/`
> 作用：协议与本地接入的参考脚本，**主流程不使用**。

## 1. 目录清单

| 文件 | 行数 | 角色 |
|------|------|------|
| `xtquant_api.py` | ~190 | 完整 XtQuant 客户端示例（GBK 编码、中文注释乱码） |
| `demo_rpc_client.py` | ~140 | RabbitMQ + MsgPacket 客户端示例 |
| `demo_builder.py` | ~190 | MsgPacket 多结果集打包/解包示例 |

## 2. `xtquant_api.py` — 迅投 QMT 完整示例

### 2.1 编码
- 文件编码为 `gbk`（中文注释在 UTF-8 终端会乱码）

### 2.2 关键内容
- 自定义 `MyXtQuantTraderCallback`，完整实现 7 个回调
- 7 档委托字段：
  ```
  account_type, account_id, stock_code, order_id, order_sysid,
  order_time, order_type, order_volume, price_type, price,
  traded_volume, traded_price, order_status, status_msg,
  strategy_name, order_remark
  ```
- `try_connect`：在 session_id 范围 [100,120) 内随机尝试连接
- `xt_trader.run_forever()` 阻塞保活

### 2.3 与项目代码的关系
- 项目实际使用的简化版是 `server/services/xtquant.py`
- `xtquant_api.py` 提供了**生产级**参考（重连、批量查询、撤单）

## 3. `demo_rpc_client.py` — RabbitMQ 客户端示例

### 3.1 三队列拓扑
```python
QUEUE_REQ    = "EvTrade.Test.Req"     # 请求
QUEUE_REPLY  = "EvTrade.Test.Reply"   # 应答
QUEUE_PUSH   = "EvTrade.Test.Push"    # 推送
```

### 3.2 流程
1. `aio_pika.connect_robust(RABBITMQ_URL)`
2. 声明 topic 交换机 `msgpacket.exchange`（durable）
3. 声明三个 durable 队列
4. 并行启动 `listen_replies` / `listen_pushs` 两个协程
5. 循环发送 `ord_stk` 请求包到 `QUEUE_REQ`
6. 收到 Ctrl+C 后等待 10s 处理剩余消息

### 3.3 报文样例（`resp_pkt_ord`）
```python
MsgPacket(REQUEST, "V1.0")
  set_func("ord_stk")
  set_headers(5, "stock_code,volume,price_type,price,direction")
  add_row()
  set_value("stock_code", "000001.SZ")
  set_value("volume", "1000")
  set_value("price_type", "0")
  set_value("price", "11.12")
  set_value("direction", "BUY")
  set_value("remark", "xtquant_test")
  finalize()
```

> 与 `server/rpc/client.py:ord_stk` 同构但 price_type 用裸数字（"0"），项目侧用 `'LIMIT' / 'LATEST' / 'FAIR'` 字符串。需与柜台约定统一。

## 4. `demo_builder.py` — MsgPacket 多结果集示例

### 4.1 演示内容
- 构建 `REQUEST` 包：`subscribe`，含 3 个结果集
  - RS1: `Symbol,Price`（2 行）
  - RS2: `Tag,Note`（1 行）
  - RS3: `Ext1,Ext2`（3 行）
- 编码后 `decode + iterate` 验证
- 构造 `ANSWER` 包回放，error_code/error_msg + Tag/Note

### 4.2 关键 API 演示
```python
pkt.set_func("subscribe")
pkt.add_result_set()        # 新结果集
pkt.next_result_set()       # 切换
pkt.select_result_set(n)    # 1-based 选择
pkt.result_set_count()
pkt.add_row() / set_value(k, v)
pkt.reset_cursor() / fetch_next() / current_row() / get_value(k)
pkt.finalize() / wire_data_bytes() / wire_to_string()
```

### 4.3 与项目的关系
- `server/rpc/client.py` 的 `_parse_*` 函数即对应"解码 + 多结果集遍历"模式
- 所有 `get_value_str(key)` 都对应该 demo 的 `get_value(key)`

## 5. MsgPacket 协议速查

来源：`README.md`（仓库根目录）

### 5.1 消息类型
| 常量 | 值 | 含义 |
|------|----|------|
| `MSG_TYPE_REQUEST` | `0x52` ('R') | 请求包 |
| `MSG_TYPE_ANSWER` | `0x41` ('A') | 应答包 |
| `MSG_TYPE_PUSH` | `0x50` ('P') | 推送包 |
| `MSG_TYPE_HEARTBEAT` | `0x48` ('H') | 心跳包 |

### 5.2 Wire 格式
```
偏移 0   : magic[4]     = "YSWY"
偏移 4   : crc32[4]     = LE
偏移 8   : body_len[4]  = LE
偏移 12  : msg_header_t (72 字节)
偏移 83  : body[]       = 柔性数组
总长     : 83 + body_len
```

### 5.3 转义规则
| 原始字节 | 编码后 |
|----------|--------|
| `0x1F` (US) | `0x1B 0x5F` |
| `0x1E` (RS) | `0x1B 0x5E` |
| `0x1C` (FS) | `0x1B 0x5C` |
| `0x1B` (ESC) | `0x1B 0x5B` |
| `0x1D` (GS) | `0x1B 0x5D` |

### 5.4 错误码
- 略（详见 README.md），典型：
  - `-1` 空指针参数
  - `-2` magic 不匹配
  - `-3` CRC32 失败
  - `-8` 无数据
  - `-9` body > 1MB
  - `-13` 协议版本不匹配

## 6. 项目侧与 iquant 目录的差异

| 项 | 项目（`server/`） | `iquant/` |
|----|-------------------|-----------|
| 接入 | FastAPI + aio_pika 客户端 | 独立 demo 脚本 |
| 行情+交易 | `xtquant.py`（轻量） / `rpc/client.py`（远端） | `xtquant_api.py`（完整本地） |
| 编码 | UTF-8 | GBK（部分） |
| 会话 ID | 100 | 100~120 随机 |
| 报文字段 | `stock_code, volume, price_type, price, direction`（5 个） | 同 + `remark`（6 个） |

## 7. 引入新字段的 checklist

修改 `ord_stk` 报文时：
1. `server/rpc/client.py:ord_stk` 同步 `set_headers` + `set_value`
2. `iquant/demo_rpc_client.py:resp_pkt_ord` 同步
3. 通知柜台（消息生产者）保持一致
4. 更新 `cross/04_iquant.md`（本文件）
