"""
server/services/script_strategy/params.py — param_ranges 类型驱动展开 (v123 D5)

职责单一: 把参数扫描请求 (param_ranges) 按脚本 params_schema 类型展开成组合。
- int/float: start..end 步进 step 含端点 (未对齐 step 的 end 不包含)
- choice:    值列表每个值一组
- string:    固定值, 不参与扫描
- 组合数 > 512 → GRID_TOO_LARGE 拒绝; 字段不在 schema → UNKNOWN_PARAM
纯逻辑, 无 DB 写入。
"""
import itertools
from typing import Any, Dict, List

from server.services.script_strategy.errors import StrategyError


def _expand_values(spec: Dict[str, Any]) -> List[Any]:
    """单参取值序列: int/float 步进含端点, choice 值列表, string 固定."""
    t = spec.get("type")
    if t in ("int", "float"):
        start = float(spec["start"])
        end = float(spec["end"])
        step = float(spec.get("step") or 1)
        vals = []
        v = start
        while v <= end:
            vals.append(int(round(v)) if t == "int" else round(v, 10))
            v += step
        return vals
    if t == "choice":
        return list(spec.get("values") or [])
    if t == "string":
        return [spec.get("value", spec.get("default", ""))]
    raise StrategyError("INVALID_PARAM_RANGE", f"不支持的参数类型: {t!r}")


def expand_param_ranges(
    param_ranges: Dict[str, Dict[str, Any]], schema: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """展开参数扫描: 参与字段笛卡尔积 + 未参与字段取 schema default 固定值.

    Returns:
        {"combos": [...], "total_runs": int, "sweep_keys": [...], "over_soft_limit": bool}
    Raises:
        StrategyError: GRID_TOO_LARGE (>512) / UNKNOWN_PARAM
    """
    schema_by_key = {s.get("key"): s for s in schema}
    for key in param_ranges:
        if key not in schema_by_key:
            raise StrategyError("UNKNOWN_PARAM", f"字段 {key!r} 不在脚本 params_schema 中")

    values_per_key: Dict[str, List[Any]] = {}
    for key, spec in param_ranges.items():
        spec = dict(spec)
        spec.setdefault("type", schema_by_key[key].get("type", "int"))
        values_per_key[key] = _expand_values(spec)

    sweep_keys = list(values_per_key.keys())
    if sweep_keys:
        combos = [
            dict(zip(sweep_keys, combo))
            for combo in itertools.product(*[values_per_key[k] for k in sweep_keys])
        ]
    else:
        combos = [{}]
    total_runs = len(combos)
    if total_runs > 512:
        raise StrategyError("GRID_TOO_LARGE", f"组合数 {total_runs} 超过硬上限 512")

    fixed = {s.get("key"): s.get("default") for s in schema if s.get("key") not in values_per_key}
    full_combos = [{**fixed, **c} for c in combos]
    return {
        "combos": full_combos,
        "total_runs": total_runs,
        "sweep_keys": sweep_keys,
        "over_soft_limit": total_runs > 64,
    }


def validate_params_keys(params: Dict[str, Any], schema_by_key: Dict[str, Any]) -> None:
    """校验单次回测 params 字段都 ∈ params_schema, 否则 UNKNOWN_PARAM."""
    for key in params:
        if key not in schema_by_key:
            raise StrategyError("UNKNOWN_PARAM", f"字段 {key!r} 不在脚本 params_schema 中")
