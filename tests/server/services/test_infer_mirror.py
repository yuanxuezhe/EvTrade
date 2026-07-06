"""
test_infer_mirror.py — 前后端 infer 镜像一致性测试 (v13 optimize-push-data-flow)

目的: 防止 server/services/order_status.py::_infer_order_status 与
      client/src/utils/format.js::inferOrderStatus 各自演进后产生 drift.

机制: 同一组 (~12 case) 输入, Python 跑 _infer_order_status,
      Node.js 子进程跑真实 format.js::inferOrderStatus, 两者输出必须 == expected.

⚠️ runner 必须 import 真实 format.js, 不能复制函数 (否则测的是"两份本地代码一致"
   而不是"前后端 infer 逻辑一致"). 跨端 drift 检测的有效性依赖于此.

执行: pytest tests/server/services/test_infer_mirror.py
依赖: Node.js 在 PATH (项目已装 vitest, 自带 node)

按 memory feedback_testing_mirror.md: 前端镜像后端的纯函数必须配跨端一致性测试.
"""
import json
import os
import subprocess
import sys

import pytest

from server.repo.orders import _infer_order_status


# 12 case 覆盖全部 4 段推断规则 + 终态保持
# 格式: (order_dict, broker_status_or_None, expected_status)
CASES = [
    # 1. 终态保持: 已经是 broker 54 (已撤), 不会被覆盖
    ({"status": "54", "volume": 100, "traded_volume": 0, "cancelled_volume": 100}, None, "54"),
    # 2. 终态保持: broker 56 (已成) 不会被 trd_cfm 覆盖
    ({"status": "56", "volume": 100, "traded_volume": 100, "cancelled_volume": 0}, None, "56"),
    # 3. 撤单主轴: cumCancelled >= vol → broker 54 (已撤)
    ({"status": "48", "volume": 100, "traded_volume": 0, "cancelled_volume": 100}, None, "54"),
    # 4. 撤单主轴: cumCancelled > 0 && cum > 0 → broker 53 (部成部撤)
    ({"status": "48", "volume": 100, "traded_volume": 30, "cancelled_volume": 50}, None, "53"),
    # 5. 撤单主轴: cumCancelled > 0 && cum == 0 → broker 54 (部分撤单无成交)
    ({"status": "48", "volume": 100, "traded_volume": 0, "cancelled_volume": 30}, None, "54"),
    # 6. broker 撤单类信号 51, cum 0 → broker 54
    ({"status": "48", "volume": 100, "traded_volume": 0, "cancelled_volume": 0}, "51", "54"),
    # 7. broker 撤单类信号 51, cum < vol → broker 53
    ({"status": "48", "volume": 100, "traded_volume": 30, "cancelled_volume": 0}, "51", "53"),
    # 8. broker 撤单类信号 51, cum == vol → broker 56 (broker 撤单无意义)
    ({"status": "48", "volume": 100, "traded_volume": 100, "cancelled_volume": 0}, "51", "56"),
    # 9. 累计推断: cum 0 → broker 50 (已报)
    ({"status": "48", "volume": 100, "traded_volume": 0, "cancelled_volume": 0}, None, "50"),
    # 10. 累计推断: cum < vol → broker 55 (部成)
    ({"status": "48", "volume": 100, "traded_volume": 30, "cancelled_volume": 0}, None, "55"),
    # 11. 累计推断: cum == vol → broker 56 (已成)
    ({"status": "48", "volume": 100, "traded_volume": 100, "cancelled_volume": 0}, None, "56"),
    # 12. 边界: volume=0 应走 cum==0 分支返 50 (防御性, 实际不会出现)
    ({"status": "48", "volume": 0, "traded_volume": 0, "cancelled_volume": 0}, None, "50"),
]


class _MockOrder:
    """Mock SQLAlchemy Order, _infer_order_status 只读 4 个字段"""
    def __init__(self, **kw):
        self.status = kw.get('status', '48')
        self.volume = kw.get('volume', 0)
        self.traded_volume = kw.get('traded_volume', 0)
        self.cancelled_volume = kw.get('cancelled_volume', 0)


_RUNNER_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'infer_mirror_runner.mjs',
)


def _run_js_infer(order_dict, broker_status):
    """调 Node.js 子进程跑前端 inferOrderStatus"""
    payload = json.dumps({'order': order_dict, 'brokerStatus': broker_status})
    # Python 3.6 兼容: 用 stdout=PIPE / stderr=PIPE / universal_newlines=True
    # (Python 3.7+ 的 capture_output / text 参数在 3.6 上不存在)
    proc = subprocess.run(
        ['node', _RUNNER_PATH],
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        timeout=5,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Node runner failed (rc={proc.returncode}): {proc.stderr}"
        )
    return proc.stdout.strip()


@pytest.mark.parametrize("order,broker_status,expected", CASES)
def test_infer_mirror_python(order, broker_status, expected):
    """Python 端: _infer_order_status 单测"""
    py_result = _infer_order_status(_MockOrder(**order), broker_status)
    assert py_result == expected, (
        f"Python _infer_order_status({order}, broker={broker_status}) "
        f"returned {py_result!r}, expected {expected!r}"
    )


@pytest.mark.parametrize("order,broker_status,expected", CASES)
def test_infer_mirror_js(order, broker_status, expected):
    """JS 端: 真实 import format.js::inferOrderStatus, 通过 Node.js 子进程"""
    js_result = _run_js_infer(order, broker_status)
    assert js_result == expected, (
        f"JS inferOrderStatus({order}, broker={broker_status}) "
        f"returned {js_result!r}, expected {expected!r}"
    )


@pytest.mark.parametrize("order,broker_status,expected", CASES)
def test_infer_mirror_consistent(order, broker_status, expected):
    """跨端一致性: Python 与 JS 必须产生相同 status (drift 检测核心)"""
    py_result = _infer_order_status(_MockOrder(**order), broker_status)
    js_result = _run_js_infer(order, broker_status)
    assert py_result == js_result, (
        f"infer mirror drift detected! order={order} broker={broker_status}\n"
        f"  Python _infer_order_status: {py_result!r}\n"
        f"  JS    inferOrderStatus:    {js_result!r}\n"
        f"  同步两侧 (server/services/order_status.py + client/src/utils/format.js)"
    )


if __name__ == '__main__':
    # 允许直接 python 跑 (调试用)
    sys.exit(pytest.main([__file__, '-v']))
