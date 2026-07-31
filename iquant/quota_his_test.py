# coding: gbk
"""
==============================================================================
Client demo: send his_hq request with configurable `fields` / `period`,
consume all per-day replies and merge into a single pandas DataFrame.
==============================================================================
"""

import io
from msgpacket import MSG_TYPE_REQUEST, MsgPacket
import pandas as pd
import pika

MQ_HOST = "192.168.10.2"
MQ_PORT = 5672
MQ_USER = "guest"
MQ_PASS = "guest"
EXCHANGE_NAME = "quota_his.exchange"
REQ_QUEUE = "EvTrade.Testgs.ReqHisHq"
ANS_QUEUE = "MyClient.AnsQueue.001"   # client-only answer queue

# ---------------------------------------------------------------------------
# Request knobs (tweak as needed)
#   FIELDS : comma-separated column names; empty string = service default "close"
#   PERIOD : tick / 1m / 5m / 15m / 30m / 1h / 1d  (must match xtquant valid set)
# ---------------------------------------------------------------------------
FIELDS = "open,close,volume"
PERIOD = "1d"


def _parse_day_payload(raw_text):
    """Split col_header from rows, return (columns:list[str], day_df:DataFrame).

    Wire format per day (returned by server):
        <col_header>\n<row1>|<row2>|...
    where row_i = "<stime>#<field1>#<field2>..."
    """
    header_line, _, body = raw_text.partition("\n")
    columns = header_line.split(",")            # ["stime", field1, field2, ...]
    if not body.strip():
        return columns, pd.DataFrame(columns=columns)
    csv_data = body.replace("|", "\n").replace("#", ",")
    day_df = pd.read_csv(io.StringIO(csv_data), names=columns)
    return columns, day_df


def send_request_and_receive():
    # 1. RabbitMQ connection
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
    channel.queue_declare(queue=ANS_QUEUE, durable=True)

    # 2. Build request packet
    req_pkt = MsgPacket(MSG_TYPE_REQUEST)
    req_pkt.set_func("his_hq")

    req_pkt.set_headers(6, "stock_code,start_date,end_date,ans_queue,fields,period")
    req_pkt.add_row()
    req_pkt.set_value("stock_code", "159992.SZ")
    req_pkt.set_value("start_date", "20220101")
    req_pkt.set_value("end_date", "20220729")
    req_pkt.set_value("ans_queue", ANS_QUEUE)
    req_pkt.set_value("fields", FIELDS)
    req_pkt.set_value("period", PERIOD)
    req_pkt.finalize()

    _, req_bytes = req_pkt.encode()

    # 3. Publish request
    channel.basic_publish(
        exchange=EXCHANGE_NAME, routing_key=REQ_QUEUE, body=req_bytes
    )
    print(f"[client] request published to {REQ_QUEUE}; waiting for replies "
          f"(fields='{FIELDS}', period='{PERIOD}')...")

    # 4. Consume all per-day replies, accumulate into one DataFrame
    merged_df = pd.DataFrame()
    for method_frame, properties, body in channel.consume(
        queue=ANS_QUEUE, inactivity_timeout=10
    ):
        if body is None:
            print("[client] no more data (timeout).")
            break

        raw_text = body.decode("utf-8")
        columns, day_df = _parse_day_payload(raw_text)
        if day_df.empty:
            channel.basic_ack(delivery_tag=method_frame.delivery_tag)
            continue

        print(f"[client] received 1 day, rows={len(day_df)}, cols={columns}")
        merged_df = pd.concat([merged_df, day_df], ignore_index=True)

        channel.basic_ack(delivery_tag=method_frame.delivery_tag)

    # 5. Final merged view
    if not merged_df.empty:
        # Make stime the index for nicer tabular display
        if "stime" in merged_df.columns:
            merged_df = merged_df.set_index("stime")
        print(f"\n[client] merged DataFrame across all days (rows={len(merged_df)}):")
        print(merged_df)
    else:
        print("[client] empty result set.")

    channel.cancel()
    conn.close()


if __name__ == "__main__":
    send_request_and_receive()