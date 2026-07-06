"""
server.infra — 基础设施基类层

职责：封装第三方依赖（aio_pika / SQLAlchemy）的细节，对上层只暴露纯接口。

包含：
- mq.py:  MessageQueueClient（aio_pika RMQ 长连接基类）
- db.py:  DatabaseBase / SessionLocal / get_db / db_session / init_db

依赖方向：本层禁止 import 任何上层（api / services / rpc / repo）。
"""
