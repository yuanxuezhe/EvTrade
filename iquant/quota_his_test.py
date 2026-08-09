# coding: gbk
"""
==============================================================================
Client demo: streaming-style per-quote callback over batch RPC replies.

his_hq 服务端按"天"批量回包 (one day per AMQP reply, 多 row 拼一行
"<row1>|<row2>|..."). demo 这里把每条 reply 拆成单 row, 每 row 触发一次
on_quote(columns, row_dict) 回调 — 模拟"实时行情一条条到达"的场景,
便于用户在 callback 里:
  - 增量 append 到本地 pandas.DataFrame
  - 算 MA / rolling / 等技术指标 (每收一笔重算最新一根)
  - 触发下单 / 报警 / 日志 等

调用方式:
  send_request_and_consume(on_quote=my_handler)
  my_handler(columns:list[str], row:dict[str,str]) -> None
==============================================================================
"""

import datetime
import io
import time
import uuid
from msgpacket import MSG_TYPE_REQUEST, MsgPacket
import pandas as pd
import pika

# TongDaXin 1m 策略 (同目录 module, 直接 import)
from strategy_runner import make_strategy_runner

MQ_HOST = "192.168.10.2"
MQ_PORT = 5672
MQ_USER = "guest"
MQ_PASS = "guest"
EXCHANGE_NAME = "quota_his.exchange"
REQ_QUEUE = "EvTrade.ReqHisHq"
# Answer queue must be unique per run (NOT a fixed durable queue):
# leftovers from a previous run would be replayed first on the next run,
# causing stale/reordered/duplicate rows even though the market data flows.

# ---------------------------------------------------------------------------
# Request knobs (tweak as needed)
#   FIELDS : comma-separated column names; empty string = service default "close"
#   PERIOD : tick / 1m / 5m / 15m / 30m / 1h / 1d  (must match xtquant valid set)
# ---------------------------------------------------------------------------
FIELDS = "open,close,high,low"
PERIOD = "1m"

STOCK_CODE = "159992.SZ"
START_DATE = "20260701"
END_DATE = "20260731"


def _unique_ans_queue() -> str:
    """Unique per-run answer queue name; deleted by the caller when done.

    The server publishes one reply per trading day to this queue by name.
    A fixed name would leave yesterday's unconsumed replies around, and the
    next run would drain those leftovers before the fresh replies.
    """
    return "MyClient.AnsQueue." + uuid.uuid4().hex[:8]


def _expected_trading_days() -> int:
    """Weekday count in [START_DATE, END_DATE] as an upper bound of replies.

    The server emits one reply per trading day (holidays / no-data days are
    skipped), so actual replies <= weekday count. Used only to print progress
    and to early-stop once all days in range are received.
    """
    start = datetime.datetime.strptime(START_DATE[:8], "%Y%m%d").date()
    end = datetime.datetime.strptime(END_DATE[:8], "%Y%m%d").date()
    return sum(
        1
        for i in range((end - start).days + 1)
        if (start + datetime.timedelta(days=i)).weekday() < 5
    )


def _iter_rows(raw_text):
    """Yield (columns, row_dict) per row from one day payload.

    Wire format (returned by server):
        <col_header>\\n<row1>|<row2>|...
    where row_i = "<stime>#<field1>#<field2>..."

    一条 AMQP reply 内可能含多 row, 本函数把它拆成多次 yield,
    让调用方按"一行一回调"处理, 模拟流式行情。

    Yields:
        (columns, row) where
            columns : list[str]  e.g. ["stime", "open", "close", "high", "low"]
            row     : dict[str, str]  e.g. {"stime": "20260701130000",
                                            "open": "1.234",
                                            "close": "1.236", ...}
    """
    header_line, _, body = raw_text.partition("\n")
    columns = header_line.split(",")
    if not body.strip():
        return
    for line in body.split("|"):
        if not line:
            continue
        values = line.split("#")
        yield columns, dict(zip(columns, values))


def _connect_and_setup(ans_queue):
    """建 AMQP 连接 + 声明 exchange/queue/binding, 返回 (conn, channel)."""
    credentials = pika.PlainCredentials(MQ_USER, MQ_PASS)
    conn = pika.BlockingConnection(
        pika.ConnectionParameters(
            host=MQ_HOST, port=MQ_PORT, credentials=credentials, socket_timeout=5
        )
    )
    channel = conn.channel()
    channel.exchange_declare(
        exchange=EXCHANGE_NAME, exchange_type="topic", durable=True
    )
    channel.queue_declare(queue=REQ_QUEUE, durable=True)
    channel.queue_bind(
        queue=REQ_QUEUE, exchange=EXCHANGE_NAME, routing_key=REQ_QUEUE
    )
    # durable=True must match the server's queue_declare(target, durable=True),
    # otherwise the server gets a 406 PRECONDITION_FAILED and never replies.
    channel.queue_declare(queue=ans_queue, durable=True)
    return conn, channel


def _build_request_packet(ans_queue):
    """Build his_hq request MsgPacket (stock_code / date / fields / period)."""
    pkt = MsgPacket(MSG_TYPE_REQUEST)
    pkt.set_func("his_hq")
    pkt.set_headers(6, "stock_code,start_date,end_date,ans_queue,fields,period")
    pkt.add_row()
    pkt.set_value("stock_code", STOCK_CODE)
    pkt.set_value("start_date", START_DATE)
    pkt.set_value("end_date", END_DATE)
    pkt.set_value("ans_queue", ans_queue)
    pkt.set_value("fields", FIELDS)
    pkt.set_value("period", PERIOD)
    pkt.finalize()
    return pkt


def send_request_and_consume(
    on_quote=None,
    inactivity_timeout=30,
    *,
    verbose=True,
):
    """发请求 + 消费所有 reply + 逐行回调 on_quote。

    Args:
        on_quote: Optional[Callable[[List[str], Dict[str, str]], None]]
                  每条 row 触发一次回调, 入参是 (columns, row_dict).
                  用户在 callback 里:
                    - 维护自己的 pandas.DataFrame (df.append / pd.concat)
                    - 算 MA / rolling / 等指标
                    - 触发下单 / 报警 等
                  传 None 时仅打印 (调试模式).
        inactivity_timeout: AMQP consume 无消息超时秒数, 超时即退出收包循环。
        verbose: 是否打印每条 row + 最终汇总。

    Returns:
        int: 累计回调次数 (收到的 row 总数).
    """
    ans_queue = _unique_ans_queue()
    expected_days = _expected_trading_days()
    conn, channel = _connect_and_setup(ans_queue)
    try:
        pkt = _build_request_packet(ans_queue)
        _, req_bytes = pkt.encode()

        channel.basic_publish(
            exchange=EXCHANGE_NAME, routing_key=REQ_QUEUE, body=req_bytes
        )
        if verbose:
            print("[client] request published to " + REQ_QUEUE +
                  " (stock=" + STOCK_CODE + ", " + START_DATE + "~" + END_DATE +
                  ", fields='" + FIELDS + "', period='" + PERIOD +
                  "', ans_queue=" + ans_queue +
                  "); waiting for replies (<= " + str(expected_days) +
                  " trading days in range)...")

        total_rows = 0
        reply_count = 0
        for method_frame, properties, body in channel.consume(
            queue=ans_queue, inactivity_timeout=inactivity_timeout
        ):
            if body is None:
                if verbose:
                    print("[client] no more data (idle " + str(inactivity_timeout) +
                          "s). replies=" + str(reply_count) + "/" + str(expected_days) +
                          " trading days, total rows: " + str(total_rows))
                break

            raw_text = body.decode("utf-8")
            # 一条 reply 内可能含多 row — 拆成单 row 回调
            row_count_in_reply = 0
            for columns, row in _iter_rows(raw_text):
                if on_quote is not None:
                    on_quote(columns, row)
                total_rows += 1
                row_count_in_reply += 1

            reply_count += 1

            if verbose:
                print("[client] reply " + str(reply_count) + "/" + str(expected_days) +
                      " parsed into " + str(row_count_in_reply) +
                      " rows (cumulative=" + str(total_rows) + ")")

            channel.basic_ack(delivery_tag=method_frame.delivery_tag)

            if reply_count >= expected_days:
                if verbose:
                    print("[client] all expected trading days received (" +
                          str(reply_count) + ")")
                break

        return total_rows
    finally:
        try:
            channel.cancel()
        except Exception:
            pass
        # unique per-run answer queue: delete it so leftover replies do not
        # pollute any future run
        try:
            channel.queue_delete(queue=ans_queue)
        except Exception:
            pass
        conn.close()


# ===========================================================================
# Demo callback: 增量收集到 pandas + 算 MA5
# ===========================================================================
def make_demo_collector(verbose=True):
    """返回一个 on_quote 回调: 每次收一条 row 就 append 到 df, 满 5 根算 MA5。

    用 closure + state 字典持有 df 引用 (避免全局变量), 调用方通过
    cb.get_df() 拿最新 DataFrame:
        cb = make_demo_collector()
        send_request_and_consume(on_quote=cb)
        # cb.get_df() 是最终 DataFrame (state 引用, 始终最新)
    """
    state = {"df": pd.DataFrame(), "warmup": 0}

    def _on_quote(columns, row):
        # 第一次回调时拿列名初始化空 df
        if state["df"].empty:
            state["df"] = pd.DataFrame(columns=columns)

        # 单行 append (转 dict 后 concat, 兼容任意列顺序)
        state["df"] = pd.concat(
            [state["df"], pd.DataFrame([row])], ignore_index=True
        )

        stime = row.get("stime", "?")
        close = row.get("close", "")
        n = len(state["df"])

        if n < 5:
            state["warmup"] += 1
            if verbose:
                print("[quote #" + str(n).rjust(4) + "] " + stime +
                      " close=" + close + " (warmup " + str(n) + "/5)")
        else:
            # rolling MA5 on close
            close_series = state["df"]["close"].astype(float)
            ma5 = close_series.rolling(5).mean().iloc[-1]
            # 同时打印 MA3 演示多周期
            ma3 = close_series.rolling(3).mean().iloc[-1]
            if verbose:
                print("[quote #" + str(n).rjust(4) + "] " + stime +
                      " close=" + close +
                      " MA3=" + format(ma3, ".4f") +
                      " MA5=" + format(ma5, ".4f"))

    # 暴露 df getter (state 是 dict, 引用始终指向最新)
    _on_quote.get_df = lambda: state["df"]
    _on_quote.get_warmup_count = lambda: state["warmup"]
    return _on_quote


def _chain_callbacks(*cbs):
    """把多个 on_quote 串成一个 (复用同一份行情流). 各 cb state 独立."""
    def _on_quote(columns, row):
        for cb in cbs:
            cb(columns, row)
    return _on_quote


if __name__ == "__main__":
    print("=" * 70)
    print("his_hq streaming demo — " + STOCK_CODE + " " + START_DATE + "~" + END_DATE +
          " period=" + PERIOD + " fields=" + FIELDS)
    print("=" * 70)

    handler = make_demo_collector(verbose=True)
    strat = make_strategy_runner()
    cb = _chain_callbacks(handler, strat)
    total = send_request_and_consume(on_quote=cb, verbose=True)

    print()

    # === PDF 黄金短线策略 事件流 (同一份行情 chain) ===
    sigs = strat.get_signals()
    st = strat.get_state()
    entries_buy = sum(1 for s in sigs if s["event"] == "ENTRY" and s["side"] == "BUY")
    entries_sell = sum(1 for s in sigs if s["event"] == "ENTRY" and s["side"] == "SELL")
    stops = sum(1 for s in sigs if s["event"] == "STOP")
    tps = sum(1 for s in sigs if s["event"] == "TP")
    realized_pnl = sum(s.get("pnl", 0) for s in sigs if s["event"] in ("STOP", "TP"))
    print()
    print("[strategy TF1=" + str(st["tf1"]) +
          " slow=" + str(st["slow"]) +
          " ATR=" + str(st["atr_period"]) +
          " bars=" + str(st["bar_count"]) +
          " events=" + str(len(sigs)) +
          " ENTRY_L=" + str(entries_buy) +
          " ENTRY_S=" + str(entries_sell) +
          " STOP=" + str(stops) +
          " TP=" + str(tps) +
          " pnl=" + format(realized_pnl, ".4f") + "]")
    if sigs:
        print("  event  stime             side  price     stop       tp        pnl       up1     dw1")
        for s in sigs:
            stop_s = format(s.get("stop", 0), ".4f")
            tp_s = format(s.get("tp", 0), ".4f")
            pnl_s = format(s.get("pnl", 0), ".4f")
            print("  " + s["event"].ljust(6) +
                  " " + s["stime"] +
                  "  " + s["side"].ljust(4) +
                  " " + format(s["price"], ".4f").rjust(7) +
                  "  " + stop_s.rjust(8) +
                  "  " + tp_s.rjust(8) +
                  "  " + pnl_s.rjust(8) +
                  "  " + format(s["up1"], ".4f").rjust(6) +
                  "  " + format(s["dw1"], ".4f").rjust(6))
    
    print("=" * 70)
    final_df = handler.get_df()
    print("Final collected DataFrame (rows=" + str(len(final_df)) + "):")
    if not final_df.empty:
        # stime 作 index 更直观
        view = final_df.set_index("stime") if "stime" in final_df.columns else final_df
        print(view.tail(10))  # 只打印最后 10 根
        # 全量 close 序列的 MA5
        if "close" in final_df.columns and len(final_df) >= 5:
            ma5_full = final_df["close"].astype(float).rolling(5).mean()
            print()
            print("MA5 (last 10):")
            print(ma5_full.tail(10).to_string())
    print("=" * 70)