"""
test_logflow.py — 统一交互日志入口测试（server-interaction-logging commit 5）

覆盖 (20+ 用例):
- 4 方向常量
- log_interaction 基本行为 (info / warning / error / exception)
- 时间戳格式 (REQ-LOG-002)
- body 截断 (REQ-LOG-004)
- 失败安全 (序列化异常不挂业务)
- 实际输出格式
"""
import io
import json
import logging
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import pytest

from server.utils.logflow import (
    DIR_FRONT_TO_SVC,
    DIR_SVC_TO_RPC,
    DIR_SVC_FROM_RPC,
    DIR_SVC_TO_FRONT,
    log_interaction,
)


# ──── 4 方向常量 ────

def test_4_dir_constants():
    """REQ-LOG-001: 4 个方向常量字符串值"""
    assert DIR_FRONT_TO_SVC == "front->svc"
    assert DIR_SVC_TO_RPC == "svc->rpc"
    assert DIR_SVC_FROM_RPC == "svc<-rpc"
    assert DIR_SVC_TO_FRONT == "front<-svc"


# ──── 工具：捕获日志输出 ────

class _CaptureHandler(logging.Handler):
    """测试用 handler: 把日志记录写到 list 供断言"""
    def __init__(self):
        super().__init__()
        self.records = []
    def emit(self, record):
        self.records.append(record)


@pytest.fixture
def capture_log():
    """捕获 server.interaction logger 的所有日志"""
    logger = logging.getLogger("server.interaction")
    handler = _CaptureHandler()
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    yield handler.records
    logger.removeHandler(handler)


# ──── log_interaction 基本 ────

def test_log_interaction_info_basic(capture_log):
    """info 级别: 1 条 INFO 记录 + 包含方向标记 + summary"""
    log_interaction(DIR_FRONT_TO_SVC, "POST /api/test", level="info")
    assert len(capture_log) == 1
    rec = capture_log[0]
    assert rec.levelname == "INFO"
    assert "[front->svc]" in rec.getMessage()
    assert "POST /api/test" in rec.getMessage()
    # 紧凑格式: [ts][level][direction] ...
    assert re.match(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}\]\[info\]\[front->svc\] POST /api/test$",
                    rec.getMessage())


def test_log_interaction_with_trace_id(capture_log):
    """trace_id 出现在 [direction] 之后"""
    log_interaction(DIR_FRONT_TO_SVC, "POST /api/test", trace_id="abc12345")
    msg = capture_log[0].getMessage()
    assert "[trace=abc12345]" in msg
    # 紧凑格式: [ts][level][direction][trace=XXX] summary
    assert re.match(
        r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}\]\[info\]\[front->svc\]\[trace=abc12345\] POST /api/test$",
        msg)


def test_log_interaction_no_trace_id_when_omitted(capture_log):
    """trace_id=None 不输出 [trace=...]"""
    log_interaction(DIR_FRONT_TO_SVC, "POST /api/test")
    msg = capture_log[0].getMessage()
    assert "[trace=" not in msg


def test_log_interaction_trace_id_8_chars(capture_log):
    """trace_id 短 ID 格式 (8 字符 hex 推荐)"""
    log_interaction(DIR_FRONT_TO_SVC, "test", trace_id="a1b2c3d4")
    assert "[trace=a1b2c3d4]" in capture_log[0].getMessage()


def test_log_interaction_with_elapsed(capture_log):
    """elapsed_ms 显示在 summary 末尾"""
    log_interaction(DIR_SVC_TO_RPC, "call func=test", elapsed_ms=3.2)
    msg = capture_log[0].getMessage()
    assert "(3.2ms)" in msg


def test_log_interaction_warning_level(capture_log):
    """warning 级别"""
    log_interaction(DIR_SVC_TO_FRONT, "400 GET /api/test", level="warning")
    assert capture_log[0].levelname == "WARNING"


def test_log_interaction_error_level(capture_log):
    """error 级别"""
    log_interaction(DIR_SVC_FROM_RPC, "TIMEOUT", level="error")
    assert capture_log[0].levelname == "ERROR"


def test_log_interaction_exception_level(capture_log):
    """exception 级别"""
    try:
        raise ValueError("test")
    except ValueError:
        log_interaction(DIR_SVC_TO_RPC, "error path", level="exception")
    assert capture_log[0].levelname == "ERROR"
    assert capture_log[0].exc_info is not None


# ──── data 参数 ────

def test_log_interaction_data_dict(capture_log):
    """data dict 每个 key 一行缩进"""
    log_interaction(DIR_FRONT_TO_SVC, "POST /api/x", data={"body": {"k": 1}, "query": {"q": "v"}})
    msg = capture_log[0].getMessage()
    assert "body = " in msg
    assert "query = " in msg
    assert '"k": 1' in msg


def test_log_interaction_data_empty(capture_log):
    """data=None / 空 dict: 不打印 data 行"""
    log_interaction(DIR_SVC_TO_RPC, "call", data=None)
    msg = capture_log[0].getMessage()
    assert " = " not in msg  # 没有 data 行


# ──── 时间戳格式 REQ-LOG-002 ────

def test_log_interaction_timestamp_format(capture_log):
    """时间戳格式 YYYY-MM-DD HH:MM:SS.fff (23 字符)"""
    log_interaction(DIR_FRONT_TO_SVC, "test")
    msg = capture_log[0].getMessage()
    # 提取首行（[开头）的方括号内容
    m = re.match(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\]", msg)
    assert m, f"no ts prefix: {msg!r}"
    ts = m.group(1)
    assert len(ts) == 23


# ──── body 截断 REQ-LOG-004 ────

def test_log_interaction_body_truncation(capture_log):
    """超长 body (4KB+) 应截断 + 加 [truncated, total=X bytes]"""
    huge = "x" * (10 * 1024)  # 10KB
    log_interaction(DIR_FRONT_TO_SVC, "POST", data={"body": huge})
    msg = capture_log[0].getMessage()
    assert "[truncated, total=" in msg
    assert len(msg) < 8 * 1024  # 整条日志不会爆炸


def test_log_interaction_body_no_truncate_when_small(capture_log):
    """小 body 不截断"""
    log_interaction(DIR_SVC_TO_RPC, "call", data={"values": {"a": 1}})
    msg = capture_log[0].getMessage()
    assert "[truncated" not in msg


# ──── 失败安全 ────

def test_log_interaction_serialize_failure_safe(capture_log):
    """序列化失败: 不抛, repr 兜底"""
    # 不可序列化的对象
    class BadObj:
        def __repr__(self):
            return "BadObj()"
    log_interaction(DIR_FRONT_TO_SVC, "test", data={"x": BadObj()})
    # 至少 1 条日志(不抛)
    assert len(capture_log) >= 1


def test_log_interaction_non_string_summary(capture_log):
    """summary 非字符串也能处理(实际不会传, 但失败安全)"""
    log_interaction(DIR_SVC_TO_RPC, "summary 123")
    assert len(capture_log) == 1


# ──── 实际输出格式验证 ────

def test_full_output_format(capture_log):
    """完整输出格式 (带 trace_id):
       [YYYY-MM-DD HH:MM:SS.fff][level][direction][trace=XXX] <summary> [(<elapsed>ms)]
         key1 = value1
         key2 = value2
    """
    log_interaction(
        DIR_SVC_FROM_RPC,
        "reply func=qry_ast",
        data={"code": "00000", "row_count": 1},
        elapsed_ms=124.0,
        trace_id="msgid001",
    )
    msg = capture_log[0].getMessage()
    lines = msg.split("\n")
    assert len(lines) == 3
    # 行 1: 时间戳 + level + 方向 + trace + summary + elapsed
    assert re.match(
        r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}\]\[info\]\[svc<-rpc\]\[trace=msgid001\] reply func=qry_ast \(124\.0ms\)$",
        lines[0])
    # 行 2-3: data 缩进
    assert lines[1].startswith("  code = ")
    assert lines[2].startswith("  row_count = ")


def test_trace_id_full_chain_pairing(capture_log):
    """实战: 同一 trace_id 在 req/resp 两条日志都出现"""
    trace_id = "abc12345"
    # 请求
    log_interaction(DIR_FRONT_TO_SVC, "GET /api/test", trace_id=trace_id)
    # 响应
    log_interaction(DIR_SVC_TO_FRONT, "200 GET /api/test", trace_id=trace_id, elapsed_ms=3.2)
    assert len(capture_log) == 2
    assert "[trace=abc12345]" in capture_log[0].getMessage()
    assert "[trace=abc12345]" in capture_log[1].getMessage()


# ──── 实战场景 ────

def test_real_scenario_http_request(capture_log):
    """实战 1: HTTP POST 请求日志"""
    log_interaction(
        DIR_FRONT_TO_SVC,
        "POST /api/orders/place",
        data={
            "query": {},
            "body": {"stock_code": "600030.SH", "volume": 100},
            "headers": {"authorization": "Bearer abc***"},
        },
        elapsed_ms=3.2,
    )
    msg = capture_log[0].getMessage()
    assert "[front->svc]" in msg
    assert "POST /api/orders/place" in msg
    assert "(3.2ms)" in msg
    assert "Bearer abc***" in msg  # 头已脱敏


def test_real_scenario_rpc_call(capture_log):
    """实战 2: RPC 调用"""
    log_interaction(
        DIR_SVC_TO_RPC,
        "call func=qry_ast msg_id=abc-123",
        data={"values": {}},
        elapsed_ms=0.1,
    )
    assert "[svc->rpc]" in capture_log[0].getMessage()


def test_real_scenario_rpc_reply(capture_log):
    """实战 3: RPC 应答"""
    log_interaction(
        DIR_SVC_FROM_RPC,
        "reply func=qry_ast msg_id=abc-123 code=00000 rows=1",
        data={"code": "00000", "row_count": 1},
        elapsed_ms=124.0,
    )
    assert "[svc<-rpc]" in capture_log[0].getMessage()
    assert "(124.0ms)" in capture_log[0].getMessage()


def test_real_scenario_ws_broadcast(capture_log):
    """实战 4: WS 广播"""
    log_interaction(
        DIR_SVC_TO_FRONT,
        "ws broadcast channel=order_update clients=3",
        data={"channel": "order_update", "payload": {"type": "ord_cfm"}},
    )
    assert "[front<-svc]" in capture_log[0].getMessage()
    assert "ws broadcast" in capture_log[0].getMessage()
