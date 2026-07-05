"""
strategy — 参数集（Regime）匹配 + 切换冷却（change strategy_trade task 5）

📖 详细 spec：openspec/changes/strategy_trade/specs/strategy/spec.md REQ-STRAT-003
📌 匹配规则：
   1. 仅考虑 enabled=True
   2. required_flags ⊆ active_flags（AND 逻辑）
   3. exclude_flags ∩ active_flags = ∅（NOT 逻辑）
   4. priority DESC → id ASC（并列取创建顺序在前）
   5. 无候选返 None（引擎暂停下单）
📌 cooldown：5 分钟内不重复切换（防抖），cooldown 期间 audit 记 'regime_cooldown'
"""
from typing import List, Optional, Set

from server.services.strategy.models import StrategyRegime


# ─────────────── 匹配 ───────────────


def match_regime(
    regimes: List[StrategyRegime],
    active_flags: Set[str],
) -> Optional[StrategyRegime]:
    """从候选 regimes 中筛 + 排序取最佳匹配

    📌 不修改传入列表；内部按 (priority DESC, id ASC) 排序副本
    📌 全部条件不满足返 None（引擎据 spec 暂停下单）
    """
    if not regimes:
        return None
    candidates = []
    for r in regimes:
        if not r.enabled:
            continue
        required = set(r.get_required_flags())
        exclude = set(r.get_exclude_flags())
        # required ⊆ active
        if not required.issubset(active_flags):
            continue
        # exclude ∩ active = ∅
        if exclude & active_flags:
            continue
        candidates.append(r)
    if not candidates:
        return None
    # 排序：priority DESC → id ASC
    candidates.sort(key=lambda r: (-(r.priority or 0), r.id or 0))
    return candidates[0]


# ─────────────── 冷却 ───────────────

COOLDOWN_SECONDS = 300  # spec 默认 5 分钟


def apply_cooldown(
    prev_regime: Optional[StrategyRegime],
    candidate: Optional[StrategyRegime],
    last_switch_ts: Optional[float],
    now_ts: float,
    cooldown: int = COOLDOWN_SECONDS,
) -> bool:
    """是否允许 regime 切换（True=切换；False=保持 prev）

    📌 决策树：
       1. prev == None              → True（首次激活）
       2. candidate == None         → False（候选为空，保持 prev）
       3. candidate.id == prev.id   → True（同 regime 不算切换）
       4. now - last_switch_ts < cooldown → False（冷却中）
       5. 否则                       → True
    📌 cooldown 默认 300s（spec）；允许测试覆盖
    📌 当 last_switch_ts=None 时（首次切换），第 4 条不阻止（视为无历史）
    """
    # 1. 首次激活
    if prev_regime is None:
        return True
    # 2. 无候选 → 不切换
    if candidate is None:
        return False
    # 3. 同 regime
    if candidate.id == prev_regime.id:
        return True
    # 4. 冷却中（last_switch_ts=None 表示无历史，直接允许）
    if last_switch_ts is not None and (now_ts - last_switch_ts) < cooldown:
        return False
    # 5. 允许
    return True


__all__ = ["match_regime", "apply_cooldown", "COOLDOWN_SECONDS"]