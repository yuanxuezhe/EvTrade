"""
server/strategy/runtime/grid.py — 参数取值范围笛卡尔积展开

📌 用法:
    schema = [
        {"key": "fast", "type": "int", "min": 3, "max": 10, "step": 1, "default": 5},
        {"key": "slow", "type": "int", "min": 15, "max": 30, "step": 5, "default": 20},
    ]
    expand_params(schema)
    → [
        {"fast": 3, "slow": 15}, {"fast": 3, "slow": 20}, {"fast": 3, "slow": 25}, {"fast": 3, "slow": 30},
        {"fast": 4, "slow": 15}, ...
    ]

📌 支持 type:
    int    → 离散整数, min/max/step
    float  → 浮点数, min/max/step
    choice → 枚举, values=[1.5, 2.0, 3.0]

📌 限制:
- 总组合数 ≤ 10000 (硬上限, 防止内存爆炸)
"""
from __future__ import annotations

from typing import Any, Dict, List

MAX_COMBINATIONS = 10000


def _expand_one(spec: Dict[str, Any]) -> List[Any]:
    """展开单个参数的所有取值"""
    t = spec.get("type", "int")
    key = spec["key"]

    if t == "choice":
        vals = spec.get("values", [])
        if not vals:
            raise ValueError(f"参数 {key!r} type=choice 但 values 为空")
        return list(vals)

    if t not in ("int", "float"):
        raise ValueError(f"参数 {key!r} 未知 type {t!r}, 只支持 int/float/choice")

    mn = spec.get("min")
    mx = spec.get("max")
    if mn is None or mx is None:
        raise ValueError(f"参数 {key!r} 必须有 min 和 max")
    step = spec.get("step", 1 if t == "int" else 0.01)
    if step <= 0:
        raise ValueError(f"参数 {key!r} step 必须 > 0")
    if mn > mx:
        raise ValueError(f"参数 {key!r} min({mn}) > max({mx})")

    vals: List[Any] = []
    v = mn
    # 浮点累加用容差比较, 防 0.1+0.2 ≠ 0.3 之类的坑
    while v <= mx + (step * 1e-6):
        vals.append(int(v) if t == "int" else float(v))
        v += step
    return vals


def expand_params(schema: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """笛卡尔积展开

    Returns:
        list[dict], 每个 dict 是一组参数值

    Raises:
        ValueError: 组合数超 MAX_COMBINATIONS
    """
    if not schema:
        return [{}]

    expanded_lists: List[List[Any]] = []
    for spec in schema:
        vals = _expand_one(spec)
        expanded_lists.append([(spec["key"], v) for v in vals])

    # 笛卡尔积
    from itertools import product
    total = 1
    for lst in expanded_lists:
        total *= len(lst)
    if total > MAX_COMBINATIONS:
        raise ValueError(
            f"参数组合数 {total} 超过上限 {MAX_COMBINATIONS}, 请缩小范围或增大 step"
        )

    result: List[Dict[str, Any]] = []
    for combo in product(*expanded_lists):
        result.append(dict(combo))
    return result


__all__ = ["expand_params", "MAX_COMBINATIONS"]