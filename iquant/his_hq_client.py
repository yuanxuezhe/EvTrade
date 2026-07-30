# coding:gbk
"""
==============================================================================
客户端 Demo（已修复连接与队列声明问题）
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
ANS_QUEUE = "MyClient.AnsQueue.001"  # 客户端专属接收队列


def send_request_and_receive():
  # 1. 建立 RabbitMQ 连接
  credentials = pika.PlainCredentials(MQ_USER, MQ_PASS)
  conn = pika.BlockingConnection(
      pika.ConnectionParameters(
          host=MQ_HOST, port=MQ_PORT, credentials=credentials, socket_timeout=5
      )
  )
  channel = conn.channel()

  # 【关键修复】显式声明 Exchange 和请求队列，防止服务端启动顺序不一致导致找不到 Exchange
  channel.exchange_declare(
      exchange=EXCHANGE_NAME, exchange_type="topic", durable=True
  )
  channel.queue_declare(queue=REQ_QUEUE, durable=True)
  channel.queue_bind(
      queue=REQ_QUEUE, exchange=EXCHANGE_NAME, routing_key=REQ_QUEUE
  )

  # 声明客户端接收应答的队列
  channel.queue_declare(queue=ANS_QUEUE, durable=True)


  # 2. 构造请求包 (使用 MsgPacket)
  req_pkt = MsgPacket(MSG_TYPE_REQUEST)
  req_pkt.set_func("his_hq")

  # RS1: 参数列表
  req_pkt.set_headers(4, "stock_code,start_date,end_date,ans_queue")
  req_pkt.add_row()
  req_pkt.set_value("stock_code", "159992.SZ")
  req_pkt.set_value("start_date", "20220101")
  req_pkt.set_value("end_date", "20220729")
  req_pkt.set_value("ans_queue", ANS_QUEUE)
  req_pkt.finalize()

  _, req_bytes = req_pkt.encode()

  # 3. 发送请求
  channel.basic_publish(
      exchange=EXCHANGE_NAME, routing_key=REQ_QUEUE, body=req_bytes
  )
  print(f"[客户端] 请求已发送至 {REQ_QUEUE}，等待接收数据...")

  # 4. 循环监听应答 (接收推送的每日数据)
  for method_frame, properties, body in channel.consume(
      queue=ANS_QUEUE, inactivity_timeout=10
  ):
    if body is None:
      print("[客户端] 超时，没有更多数据。")
      break

    # 将收到字节解码为字符串文本
    raw_text = body.decode("utf-8")

    # 解析为 Pandas DataFrame
    csv_data = raw_text.replace("|", "\n").replace("#", ",")
    columns = ["stime", "close"]
    df = pd.read_csv(io.StringIO(csv_data), names=columns)

    print(f"\n[客户端] 收到当天数据 DataFrame (共 {len(df)} 行):")
    print(df.head(len(df)))

    channel.basic_ack(delivery_tag=method_frame.delivery_tag)

  # 取消消费并关闭连接
  channel.cancel()
  conn.close()


if __name__ == "__main__":
  send_request_and_receive()