"""
server/services/script_strategy/errors.py — 业务校验错误类型

职责单一: 定义 StrategyError, 由 api 层统一映射为 400 {code, msg}。
其他子模块 (strategies / params / batches) 只从这里 import, 避免互相循环依赖。
"""


class StrategyError(ValueError):
    """业务校验错误, 由 api 层映射为 400 {code, msg}"""

    def __init__(self, code: str, msg: str):
        super().__init__(msg)
        self.code = code
        self.msg = msg
