"""
crawler — 股票信息爬虫层

目录结构:
  crawler/
    __init__.py
    sources/
      eastmoney.py    # 东方财富适配
    runner.py         # 同步循环主控

数据流:
  sync_manager.start() → runner.run(all_codes) → for code: eastmoney.fetch() → repo.upsert()
                                                              │
                                                              └─→ progress_callback(...) → WS broadcast
"""
__version__ = "1.0.0"