"""
crawler/sources — 数据源适配层

每个文件对应一个数据源:
  eastmoney.py    # 东方财富 (v21)

设计原则:
- 单一职责:每个 fetch 函数返标准 dict,异常由调用方处理
- 不持久化:本层只负责 HTTP 拉取 + 解析,不写 DB
- 反爬友好:随机 UA + sleep(由 runner 控制)
"""