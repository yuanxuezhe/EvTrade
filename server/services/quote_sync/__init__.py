"""
server/services/quote_sync — 历史行情补全 (his-quote-backfill)

server 进程自包含: 拉 broker his_hq 1m → 落地 minute_bars → 游标推进。
不 import strategy_exec (跨服务隔离), 用 server.config 现有 HIS_HQ_*。
"""
