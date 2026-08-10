#encoding: gbk
"""
QMT 行情 publisher：把 subscribe_whole_quote 收到的行情快照广播到 RabbitMQ。

优化要点：
  1. 彻底移除了锁内部的 print(line) 同步阻塞 I/O，极大地释放了 QMT 回调和 Worker 的性能。
  2. 降低 Worker 数量（16 -> 1），增大单批次吞吐量（20 -> 500），大幅减少多线程 GIL 和 asyncio 锁竞争。
  3. 优化了空仓等待机制，避免 CPU 空转。
"""
from collections import deque
import threading
import asyncio
import aio_pika


class Config:
    RABBITMQ_URL = "amqp://192.168.10.2:5672/?heartbeat=60"
    EXCHANGE_NAME = "quota.exchange"
    QUEUE_NAME = "EvQuota"      # 固定队列名
    NUM_WORKERS = 1             # 减少 Worker 数量，2个足以吞吐数万条/秒
    BATCH_SIZE = 1000            # 提升批量上限，以应对全推行情
    SNAPSHOT_INTERVAL = 0.005   # 队列空时 sleep 5毫秒，防止抢占 CPU


config = Config()


class _InvisibleStorage:
    __slots__ = ()
    inner_box = {
        "quote_queue": deque(),  # 使用双端队列，FIFO 保留每一条 LV1 切片
        "loop": None,
        "thread": None,
        "active": False,
        "token": 0,
    }
    lock = threading.Lock()


# ================================================================
# 核心异步分发 Worker (流水模式)
# ================================================================
async def quota_snapshot_worker(worker_id, exchange, auth_token):
    publish_func = exchange.publish
    print(f"[Worker-{worker_id}] 启动成功，进入 LV1 流水分发模式...", flush=True)

    while (
        _InvisibleStorage.inner_box["active"]
        and _InvisibleStorage.inner_box["token"] == auth_token
    ):
        raw_queue = None
        
        # 1. 瞬间拿锁，直接“偷走”整个 deque 并替换为新的 deque
        # 拿锁耗时 < 1 微秒，QMT 回调没有任何感知
        with _InvisibleStorage.lock:
            if _InvisibleStorage.inner_box["quote_queue"]:
                raw_queue = _InvisibleStorage.inner_box["quote_queue"]
                _InvisibleStorage.inner_box["quote_queue"] = deque()

        # 2. 在锁外处理数据并打包发布
        if raw_queue:
            batch_lines = list(raw_queue)
            
            # 按 BATCH_SIZE 打包，避免单条消息过大
            for i in range(0, len(batch_lines), config.BATCH_SIZE):
                chunk = batch_lines[i : i + config.BATCH_SIZE]
                body = "\n".join(chunk).encode("gbk")
                msg = aio_pika.Message(body, delivery_mode=1)
                try:
                    await publish_func(msg, routing_key="")
                except asyncio.CancelledError:
                    return
                except Exception as e:
                    print(f"[Worker-{worker_id}] publish error: {e}", flush=True)
                    await asyncio.sleep(0.05)
        else:
            await asyncio.sleep(config.SNAPSHOT_INTERVAL)

    print(f"[Worker-{worker_id}] 退出循环。", flush=True)
            
            
async def async_main_loop(auth_token):
    loop = asyncio.get_event_loop()
    _InvisibleStorage.inner_box["loop"] = loop

    print("[MQ-Main] 正在建立 RabbitMQ 广播连接并初始化拓扑...", flush=True)
    try:
        connection = await aio_pika.connect_robust(config.RABBITMQ_URL)
        channel = await connection.channel()
        
        exchange = await channel.declare_exchange(
            config.EXCHANGE_NAME,
            type=aio_pika.ExchangeType.FANOUT,
            durable=False,
        )

        queue = await channel.declare_queue(
            config.QUEUE_NAME,
            durable=True,
            exclusive=False
        )
        await queue.bind(exchange, routing_key="")
        print(f"[MQ-Main] 拓扑就绪：成功绑定队列 {config.QUEUE_NAME} -> 交换机 {config.EXCHANGE_NAME}", flush=True)

    except Exception as e:
        print(f"[MQ-Main] RabbitMQ 初始化拓扑失败: {e}", flush=True)
        _InvisibleStorage.inner_box["active"] = False
        return

    print(f"[MQ-Main] 启动 {config.NUM_WORKERS} 个 worker...", flush=True)

    worker_tasks = [
        loop.create_task(quota_snapshot_worker(i, exchange, auth_token))
        for i in range(config.NUM_WORKERS)
    ]

    try:
        # 维持主循环，直到外部将 active 设为 False
        while (
            _InvisibleStorage.inner_box["active"]
            and _InvisibleStorage.inner_box["token"] == auth_token
        ):
            await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        pass
    finally:
        print("[MQ-Main] 开始卸载网络拓扑与断开连接...", flush=True)
        for task in worker_tasks:
            if not task.done():
                task.cancel()
        try:
            await channel.close()
            await connection.close()
        except Exception:
            pass


def start_network_thread(auth_token):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(async_main_loop(auth_token))
    finally:
        loop.close()


def init(ContextInfo):
    _InvisibleStorage.inner_box["token"] += 1
    current_token = _InvisibleStorage.inner_box["token"]
    with _InvisibleStorage.lock:
        _InvisibleStorage.inner_box["quote_queue"].clear()
    _InvisibleStorage.inner_box["active"] = True

    _InvisibleStorage.inner_box["thread"] = threading.Thread(
        target=start_network_thread,
        args=(current_token,),
        name=f"MQ-Broadcast-{current_token}",
    )
    _InvisibleStorage.inner_box["thread"].daemon = True
    _InvisibleStorage.inner_box["thread"].start()

    # 订阅沪深 ETF/A股
    etfs = list(dict.fromkeys(ContextInfo.get_stock_list_in_sector("沪深ETF")))
    if not etfs:
        etfs = list(dict.fromkeys(ContextInfo.get_stock_list_in_sector("沪深A股")))
    print(f"[Init] 成功订阅标的数量: {len(etfs)}")
    
    # 全推订阅
    ContextInfo.subscribe_whole_quote(['SZ', 'SH'], on_quote)


# ================================================================
# QMT 同步回调：极速追加到 deque
# ================================================================
def on_quote(datas):
    if not _InvisibleStorage.inner_box["active"]:
        return
    lines = format_quote(datas)
    
    # deque.extend 是 C 级别的原生追加，极快
    with _InvisibleStorage.lock:
        _InvisibleStorage.inner_box["quote_queue"].extend(lines)


def format_quote(datas):
    """datas: {stock_code: {lastPrice, open, high, low, lastClose, volume, amount, ...}}"""
    def fmt_price(v):
        s = f"{float(v):.4f}".rstrip("0").rstrip(".")
        return s if s else "0"
        
    lines = []
    for code, q in datas.items():
        fields = [
            code,
            q.get("stime", ""),
            fmt_price(q.get("lastPrice", 0)),
            fmt_price(q.get("open", 0)),
            fmt_price(q.get("high", 0)),
            fmt_price(q.get("low", 0)),
            fmt_price(q.get("lastClose", 0)),
            fmt_price(q.get("volume", 0)),
            fmt_price(q.get("amount", 0)),
            fmt_price(q.get("openInt", 0)),
            fmt_price(q.get("transactionNum", 0)),
        ]
        for i in range(5):
            fields.append(fmt_price(q.get("askPrice", [0] * 5)[i]))
        for i in range(5):
            fields.append(fmt_price(q.get("bidPrice", [0] * 5)[i]))
        for i in range(5):
            fields.append(fmt_price(q.get("askVol", [0] * 5)[i]))
        for i in range(5):
            fields.append(fmt_price(q.get("bidVol", [0] * 5)[i]))
        lines.append("|".join(map(str, fields)))
    #print(lines)
    return lines


def stop(ContextInfo):
    print("[Stop] 正在请求安全退出...", flush=True)
    _InvisibleStorage.inner_box["active"] = False
    
    loop = _InvisibleStorage.inner_box["loop"]
    if loop and loop.is_running():
        loop.call_soon_threadsafe(lambda: None)

    if _InvisibleStorage.inner_box["thread"]:
        _InvisibleStorage.inner_box["thread"].join(timeout=3)
    
    with _InvisibleStorage.lock:
        _InvisibleStorage.inner_box["quote_queue"].clear()
        
    print("[Stop] 广播引擎已平稳、安全退出。", flush=True)








