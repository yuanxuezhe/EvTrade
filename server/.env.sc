# EvTrade backend configuration
# Copy to .env and adjust as needed.

# ---- RabbitMQ ----
EVTRADE_RABBITMQ_URL=amqp://192.168.10.2:5672/
EVTRADE_EXCHANGE_NAME=msgpacket.exchange
EVTRADE_QUEUE_REQ=EvTrade.SC.Req
EVTRADE_QUEUE_REPLY=EvTrade.SC.Reply
EVTRADE_QUEUE_PUSH=EvTrade.SC.Push

# ---- RPC ----
EVTRADE_RPC_TIMEOUT=30

# ---- FastAPI ----
EVTRADE_API_HOST=0.0.0.0
EVTRADE_API_PORT=8000
