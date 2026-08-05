"""
server/strategy/runtime/his_hq.py — 同步拉历史 K 线

📌 数据源:
- 走 RabbitMQ 到 broker (iquant runtime)
- 用 msgpacket 协议发 his_hq 请求, 同步等 reply
- 仿 iquant/quota_his_test.py 的 send_request_and_consume, 但改为同步等待全部结果

📌 协议 (参考 iquant/quota_his.py):
- exchange / req queue / timeout 由 server.config.settings 注入
  (环境变量: EVTRADE_HIS_HQ_RABBITMQ_URL / EVTRADE_HIS_HQ_EXCHANGE_NAME /
   EVTRADE_HIS_HQ_REQ_QUEUE / EVTRADE_HIS_HQ_TIMEOUT)
- 默认值兼容 iquant demo (quota_his.exchange + EvTrade.Test.ReqHisHq + 30s)
- ans queue: 客户端独占 (exclusive), 一次性
- req pkt:   func='his_hq', fields=(stock_code,start_date,end_date,ans_queue,fields,period)
- reply body: "<col_header>\n<row1>|<row2>|..."  (col_header='stime,open,close,...')
  每 row:  "<stime>#<val1>#<val2>#..."

📌 限制:
- 同步 pika, 单线程; BacktestEngine 在后台线程调, 不阻塞 event loop
- 默认 30s 超时 (broker 慢 / 大量日期时, 通过 EVTRADE_HIS_HQ_TIMEOUT 调)
- 失败返空 list (BacktestEngine 走 '未拉到历史数据' failed 路径)
"""
from __future__ import annotations

import json
import logging
import time
from typing import List, Dict, Any, Optional

import pika
from msgpacket import MsgPacket, MSG_TYPE_REQUEST

log = logging.getLogger(__name__)


# ─────────────── 配置 (从 server.config.settings 读, 无 settings 时用 iquant demo 默认值) ───────────────


def _get_config():
    """懒加载 settings (避免循环 import; settings 不存在时返默认)"""
    try:
        from server.config import settings
        return {
            "url": settings.HIS_HQ_RABBITMQ_URL,
            "exchange": settings.HIS_HQ_EXCHANGE_NAME,
            "req_queue": settings.HIS_HQ_REQ_QUEUE,
            "timeout": settings.HIS_HQ_TIMEOUT,
            "user": settings.HIS_HQ_USER,
            "password": settings.HIS_HQ_PASSWORD,
            "fallback_demo": settings.HIS_HQ_FALLBACK_DEMO,
        }
    except Exception:
        # 兜底: iquant demo 默认值 (兼容被 import 时 settings 还没初始化)
        return {
            "url": "amqp://192.168.10.2:5672/",
            "exchange": "quota_his.exchange",
            "req_queue": "EvTrade.Test.ReqHisHq",
            "timeout": 30.0,
            "user": "guest",
            "password": "guest",
            "fallback_demo": False,
        }


# ─────────────── 内部: wire protocol ───────────────


def _connect_and_setup(ans_queue: str, cfg: Dict[str, Any]):
    """连 MQ + 声明 exchange + 绑定 req queue + 声明 ans queue (一次性)

    cfg: {"url", "exchange", "req_queue", "user", "password"} — 由 _get_config() 提供
    """
    from urllib.parse import urlparse
    parsed = urlparse(cfg["url"])
    credentials = pika.PlainCredentials(cfg["user"], cfg["password"])
    conn = pika.BlockingConnection(
        pika.ConnectionParameters(
            host=parsed.hostname or "192.168.10.2",
            port=parsed.port or 5672,
            credentials=credentials, socket_timeout=5,
        )
    )
    channel = conn.channel()
    channel.exchange_declare(exchange=cfg["exchange"], exchange_type="topic", durable=True)
    channel.queue_declare(queue=cfg["req_queue"], durable=True)
    channel.queue_bind(queue=cfg["req_queue"], exchange=cfg["exchange"], routing_key=cfg["req_queue"])
    channel.queue_declare(queue=ans_queue, durable=True)
    return conn, channel


# 默认行情字段 (兼容历史 task 不设 fields 的情况)
# 默认行情字段 (兼容历史 task 不设 fields 的情况)
# 注意: broker 端 xtquant 约定用 | 分隔多字段名
#   broker handler: fields_str.split("|") 或 xtquant 内部 split
DEFAULT_FIELDS = "open|close|high|low"


def _build_request(stock_code: str, start_date: str, end_date: str,
                   ans_queue: str, fields: str, period: str) -> bytes:
    """构造 his_hq 请求 MsgPacket

    📌 headers 列数 = 6 (固定字段) + 用户选 fields 字段
       固定字段: stock_code / start_date / end_date / ans_queue / fields / period
       用户选字段: 'open,close,high,low' / 'volume' / 'amount' 等 (拼到固定字段之后)

       这样 broker 返的 reply headers 会包含 'stime' + 用户选字段,
       _parse_replies 解析时自动识别。
    """
    # 严格按 iquant quota_his_test.py: headers=6 固定字段,
    # fields 是完整逗号分隔字符串 ('open,close,high,low,volume'),
    # broker 端 split(',') 解析
    # 注意: 不能把 user fields 也加到 headers 里 (MsgPacket 用 , 分隔字段, 含逗号的值会被错拆)
    pkt = MsgPacket(MSG_TYPE_REQUEST)
    pkt.set_func("his_hq")
    pkt.set_headers(6, "stock_code,start_date,end_date,ans_queue,fields,period")
    pkt.add_row()
    pkt.set_value("stock_code", stock_code)
    pkt.set_value("start_date", start_date)
    pkt.set_value("end_date", end_date)
    pkt.set_value("ans_queue", ans_queue)
    pkt.set_value("fields", fields)  # 完整字符串
    pkt.set_value("period", period)
    pkt.finalize()
    _, body = pkt.encode()
    return body


def _parse_replies(raw_text: str) -> List[Dict[str, Any]]:
    """解 reply body → bars list

    Format:
      <col_header>\n<row1>|<row2>|...
      row_i = "<stime>#<val1>#<val2>#..."

    📌 防御性处理 (broker 数据可能不全):
      - 列名缺 close → 警告 + 返空 list (broker 格式错)
      - close=None 行 → 向前填充 (前一根 close)
      - open/high/low 任一缺失或 None → 用 close 兜底 (确保 on_bar 用户脚本访问不抛 KeyError)
      - 4 个价格字段最终保证非 None (broker 怎么奇怪用户都能拿到 0.0 fallback)
    """
    header_line, _, body = raw_text.partition("\n")
    if not body.strip():
        return []
    raw_columns = [c.strip() for c in header_line.split(",")]
    canonical_cols = [c.lower() for c in raw_columns]

    # 列名校验: close 必需 (权益计算 + on_bar)
    # 降级策略: broker 端 his_hq handler 有时不返 close (只返 stime+open 等基础字段)
    # 这时把 open 当 close 用, 让回测仍能跑 (回测出来的 PnL 仅供 demo, 不准确)
    has_close = "close" in canonical_cols
    if not has_close:
        log.warning("_parse_replies: broker 返的列名不含 close, 降级用 open 当 close (cols=%s)", raw_columns)
        canonical_cols = list(canonical_cols) + ["close"]
        # 注意: 没 close 列就靠 open 兜底, 见下面循环

    bars: List[Dict[str, Any]] = []
    for line in body.split("|"):
        if not line:
            continue
        values = line.split("#")
        d = dict(zip(canonical_cols[:len(values)], values))
        bar = {"stime": d.get("stime", "")}
        for k, v in d.items():
            if k == "stime":
                continue
            try:
                bar[k] = float(v) if v not in (None, "") else None
            except (TypeError, ValueError):
                bar[k] = None
        # 没 close 列 → 用 open 兜底
        if not has_close and "close" not in bar and bar.get("open") is not None:
            bar["close"] = bar["open"]
        bars.append(bar)

    # 价格字段兜底 (即使 broker 没返 / 值为 None, 也保证 4 字段非 None)
    # 策略: 优先用 close, 否则从前一根 bar 取 close, 否则 0
    PRICE_FIELDS = ("open", "high", "low", "close")
    last_close = None
    valid_bars: List[Dict[str, Any]] = []
    dropped_count = 0
    fallback_count = 0

    for bar in bars:
        # close 必需: 缺失则跳过
        if bar.get("close") is None:
            if last_close is None:
                # 第一根 close 就缺失, 跳过 (无法计算权益)
                dropped_count += 1
                continue
            bar["close"] = last_close
        else:
            last_close = bar["close"]

        # open / high / low: None 或缺失时用 close 兜底
        for field in ("open", "high", "low"):
            if bar.get(field) is None:
                bar[field] = bar["close"]
                fallback_count += 1

        valid_bars.append(bar)

    if dropped_count > 0:
        log.warning("_parse_replies: broker 返 %d 根 bars 中 %d 根 close 缺失已 drop",
                    len(bars), dropped_count)
    if fallback_count > 0:
        log.info("_parse_replies: %d 个 open/high/low 字段用 close 兜底 (broker 数据不全)",
                 fallback_count)

    return valid_bars


# ─────────────── demo 数据源 (broker 不响应时用) ───────────────


def _generate_demo_bars(
    stock_code: str,
    start_date: str,
    end_date: str,
    period: str = "1d",
) -> List[Dict[str, Any]]:
    """broker his_hq 不响应时, 生成模拟 K 线用于本地体验完整回测流程

    📌 真实场景: broker 192.168.10.2 通了但 his_hq handler 没挂消费者
       → fetch_his_bars 返空 → 启动 fallback demo 让回测可跑

    📌 数据特征:
       - 价格带趋势 + 噪声, 围绕 [0.8, 1.5] 浮动 (类 ETF/指数)
       - 包含 2 段上涨 + 1 段下跌, 让简单金叉死叉策略能产生交易
       - 基于 stock_code 哈希做 seed, 同标的每次返回相同数据 (确定性)
       - period 影响 bar 数 (1d=每日, 1m=每日 240 根)
    """
    import math
    import hashlib

    # 用 stock_code + 日期做 seed, 保证可复现
    seed_str = f"{stock_code}:{start_date}:{end_date}:{period}"
    seed_int = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
    import random
    rng = random.Random(seed_int)

    # 按 period 算每天 bar 数
    per_day = {"1m": 240, "5m": 48, "15m": 16, "30m": 8, "60m": 4, "1h": 4, "1d": 1}.get(period, 1)

    # 解析日期范围
    try:
        from datetime import datetime, timedelta
        sd = datetime.strptime(start_date, "%Y%m%d")
        ed = datetime.strptime(end_date, "%Y%m%d")
    except ValueError:
        log.warning("demo_bars: 日期格式错, 返空")
        return []

    if ed < sd:
        return []

    days = (ed - sd).days + 1
    total_bars = days * per_day

    if total_bars > 50000:
        log.warning("demo_bars: 数据量过大 (%d), 截断到 50000", total_bars)
        total_bars = 50000

    # 生成价格序列: 起始 1.0, 加 trend + noise
    # trend: 多段周期函数模拟"牛-震-熊-牛"
    bars = []
    price = 1.0
    base_volume = 100000 if per_day == 1 else 1000

    for i in range(total_bars):
        day_idx = i // per_day
        intra_day_idx = i % per_day

        # 日期 + 时间戳
        cur_date = sd + timedelta(days=day_idx)
        if period == "1d":
            stime = cur_date.strftime("%Y%m%d") + "1500"  # 收盘时间
        else:
            # intra-day: A 股实际交易时间 9:30-11:30 + 13:00-15:00 共 240 分钟
            # intra_day_idx 范围 0..per_day-1
            minutes_per_bar = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60, "1h": 60}[period]
            # 上午 120 分钟 + 下午 120 分钟 = 240 分钟
            if intra_day_idx < 120 // minutes_per_bar:
                # 上午段
                cur_min = 9 * 60 + 30 + intra_day_idx * minutes_per_bar
            else:
                # 下午段: intra_day_idx 0-based → 跳过午休
                after_lunch_idx = intra_day_idx - 120 // minutes_per_bar
                cur_min = 13 * 60 + after_lunch_idx * minutes_per_bar
            hh = cur_min // 60
            mm = cur_min % 60
            stime = f"{cur_date.strftime('%Y%m%d')}{hh:02d}{mm:02d}"

        # 价格变化: 多段 trend + 高斯噪声
        phase = day_idx / max(days, 1)
        # 4 段: 上涨 / 震荡 / 下跌 / 上涨
        if phase < 0.3:
            trend = 0.005  # 上涨
        elif phase < 0.5:
            trend = 0.0  # 震荡
        elif phase < 0.7:
            trend = -0.004  # 下跌
        else:
            trend = 0.006  # 二次上涨
        noise = rng.gauss(0, 0.015)
        price = max(0.5, min(2.0, price * (1 + trend + noise)))

        # OHLC: open 接近前一 close, high/low 包住 noise
        open_p = price * (1 + rng.uniform(-0.003, 0.003))
        high_p = max(open_p, price) * (1 + abs(rng.gauss(0, 0.005)))
        low_p = min(open_p, price) * (1 - abs(rng.gauss(0, 0.005)))
        close_p = price
        volume = int(base_volume * (1 + rng.uniform(-0.3, 0.5)))

        bars.append({
            "stime": stime,
            "open": round(open_p, 4),
            "high": round(high_p, 4),
            "low": round(low_p, 4),
            "close": round(close_p, 4),
            "volume": volume,
            "period": period,
        })

    log.info("demo_bars: %s %s~%s period=%s → 生成 %d bars (seed=%d)",
             stock_code, start_date, end_date, period, len(bars), seed_int)
    return bars


# ─────────────── 公共 API ───────────────


def fetch_his_bars(
    stock_code: str,
    start_date: str,
    end_date: str,
    period: str = "1d",
    fields: str = DEFAULT_FIELDS,
    timeout: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """同步拉历史 K 线

    Args:
        stock_code: e.g. '159992.SZ'
        start_date/end_date: 'YYYYMMDD'
        period: '1d' / '1m' / '5m' / etc.
        fields: 逗号分隔
        timeout: 秒 (None 时取 EVTRADE_HIS_HQ_TIMEOUT 或默认 30s)

    Returns:
        bars list [{stime, open, close, high, low, volume}, ...]
        失败 (连不上 broker / 超时) 返空 list
        若 EVTRADE_HIS_HQ_FALLBACK_DEMO=1, broker 不响应时自动切 demo 数据
    """
    if not start_date or not stock_code:
        log.warning("fetch_his_bars: 缺少 stock_code / start_date")
        return []

    cfg = _get_config()
    effective_timeout = timeout if timeout is not None else cfg["timeout"]

    # ans_queue 一次性, 用时间戳 + 随机后缀避免冲突
    import uuid
    ans_queue = f"HisAns.{uuid.uuid4().hex[:8]}"

    connection_failed = False
    try:
        conn, channel = _connect_and_setup(ans_queue, cfg)
    except Exception as e:
        log.error("fetch_his_bars: 连 MQ 失败 (url=%s req_queue=%s): %s",
                  cfg["url"], cfg["req_queue"], e)
        connection_failed = True

    all_bars: List[Dict[str, Any]] = []
    request_failed = False
    if not connection_failed:
        try:
            # 发请求
            req_bytes = _build_request(stock_code, start_date, end_date, ans_queue, fields, period)
            channel.basic_publish(
                exchange=cfg["exchange"], routing_key=cfg["req_queue"], body=req_bytes,
            )
            log.info("fetch_his_bars: 已发请求 stock=%s %s~%s period=%s → exchange=%s queue=%s",
                     stock_code, start_date, end_date, period, cfg["exchange"], cfg["req_queue"])

            # 同步消费 (broker 可能按天分段回复)
            deadline = time.time() + effective_timeout
            for method_frame, properties, body in channel.consume(
                queue=ans_queue, inactivity_timeout=min(2.0, max(0.5, deadline - time.time())),
            ):
                if body is None:
                    # inactivity timeout, 检查是否到 deadline
                    if time.time() >= deadline:
                        log.info("fetch_his_bars: timeout (%.1fs), broker 未响应", effective_timeout)
                        request_failed = True
                        break
                    continue
                try:
                    raw_text = body.decode("utf-8")
                except UnicodeDecodeError:
                    # 兼容 gbk (看 iquant 用 gbk)
                    raw_text = body.decode("gbk", errors="replace")
                bars = _parse_replies(raw_text)
                all_bars.extend(bars)
                channel.basic_ack(delivery_tag=method_frame.delivery_tag)
                # inactivity_timeout 已到 → 收尾
                if time.time() >= deadline:
                    log.info("fetch_his_bars: 时间到, 已收 %d bars", len(all_bars))
                    break
        except Exception as e:
            log.exception("fetch_his_bars: 异常: %s", e)
            request_failed = True
        finally:
            try:
                channel.cancel()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    # 排序按 stime
    all_bars.sort(key=lambda b: b.get("stime", ""))
    log.info("fetch_his_bars: broker 返回 %d bars (stock=%s %s~%s)",
             len(all_bars), stock_code, start_date, end_date)

    # Fallback demo 数据源
    if not all_bars and cfg.get("fallback_demo"):
        if connection_failed:
            reason = "连 MQ 失败"
        elif request_failed:
            reason = "broker 不响应 (his_hq handler 未挂消费者)"
        else:
            reason = "broker 返空数据"
        log.warning("fetch_his_bars: 启用 demo 数据源 (%s) → 用 _generate_demo_bars", reason)
        all_bars = _generate_demo_bars(stock_code, start_date, end_date, period=period)
        log.info("fetch_his_bars: demo 返 %d bars", len(all_bars))

    return all_bars


__all__ = ["fetch_his_bars"]