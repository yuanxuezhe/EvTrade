"""
test_regime.py — Regime 匹配 + 冷却单测（task 5）

覆盖：
- match_regime 6 种边界（单匹配 / 多候选取高 priority / 并列取小 id /
  required 缺一 / exclude 命中 / disabled / 无候选）
- apply_cooldown 4 种分支（首次 / 同 regime / 冷却内 / 冷却外）
"""
import pytest


# ─────────────── Helpers ───────────────


def _make_regime(id_, name, priority, required=None, exclude=None, enabled=True):
    """直接构造 StrategyRegime（不走 DB，绕开 FK 约束）"""
    from server.services.strategy.models import StrategyRegime
    r = StrategyRegime(id=id_, strategy_id=1, name=name, priority=priority, enabled=enabled)
    if required is not None:
        r.set_required_flags(required)
    if exclude is not None:
        r.set_exclude_flags(exclude)
    return r


# ─────────────── match_regime ───────────────


def test_match_regime_single_match():
    from server.services.strategy.regime import match_regime
    r1 = _make_regime(1, "R1", priority=10, required=["ma_bullish"])
    active = {"ma_bullish", "rsi_overbought"}
    assert match_regime([r1], active) is r1


def test_match_regime_priority_wins():
    from server.services.strategy.regime import match_regime
    r1 = _make_regime(1, "R1", priority=10, required=["ma_bullish"])
    r2 = _make_regime(2, "R2", priority=20, required=["rsi_overbought"])
    active = {"ma_bullish", "rsi_overbought"}
    assert match_regime([r1, r2], active) is r2


def test_match_regime_priority_tie_picks_smallest_id():
    from server.services.strategy.regime import match_regime
    r1 = _make_regime(1, "R1", priority=10, required=["ma_bullish"])
    r2 = _make_regime(2, "R2", priority=10, required=["ma_bullish"])
    active = {"ma_bullish"}
    # priority 并列 → id 最小者
    assert match_regime([r1, r2], active) is r1


def test_match_regime_required_missing_skipped():
    from server.services.strategy.regime import match_regime
    r1 = _make_regime(1, "R1", priority=10, required=["ma_bullish", "macd_golden_cross"])
    active = {"ma_bullish"}  # 缺 macd_golden_cross
    assert match_regime([r1], active) is None


def test_match_regime_exclude_intersect_skipped():
    from server.services.strategy.regime import match_regime
    r1 = _make_regime(1, "R1", priority=10, required=[], exclude=["ma_bearish"])
    active = {"ma_bearish", "rsi_overbought"}
    assert match_regime([r1], active) is None


def test_match_regime_disabled_skipped():
    from server.services.strategy.regime import match_regime
    r1 = _make_regime(1, "R1", priority=10, required=[], enabled=False)
    active = {"ma_bullish"}
    assert match_regime([r1], active) is None


def test_match_regime_no_match_returns_none():
    from server.services.strategy.regime import match_regime
    r1 = _make_regime(1, "R1", priority=10, required=["ma_bullish"])
    active = {"rsi_overbought"}  # 啥都不匹配
    assert match_regime([r1], active) is None


def test_match_regime_empty_list_returns_none():
    from server.services.strategy.regime import match_regime
    assert match_regime([], {"ma_bullish"}) is None


# ─────────────── apply_cooldown ───────────────


def test_apply_cooldown_first_activation_allowed():
    from server.services.strategy.regime import apply_cooldown
    # prev=None → 允许
    assert apply_cooldown(None, None, None, now_ts=1000.0) is True


def test_apply_cooldown_candidate_none_keeps_prev():
    from server.services.strategy.regime import apply_cooldown
    r1 = _make_regime(1, "R1", priority=10)
    # prev=R1, candidate=None → 不切换（保持 R1）
    assert apply_cooldown(r1, None, last_switch_ts=900.0, now_ts=1000.0) is False


def test_apply_cooldown_same_regime_allowed():
    from server.services.strategy.regime import apply_cooldown
    r1 = _make_regime(1, "R1", priority=10)
    # prev=candidate 都 R1 → 不算切换
    assert apply_cooldown(r1, r1, last_switch_ts=900.0, now_ts=910.0) is True


def test_apply_cooldown_within_window_blocks():
    from server.services.strategy.regime import apply_cooldown
    r1 = _make_regime(1, "R1", priority=10)
    r2 = _make_regime(2, "R2", priority=20)
    # 切换时刻 1000, now=1100 (差 100s < 300) → 阻止
    assert apply_cooldown(r1, r2, last_switch_ts=1000.0, now_ts=1100.0, cooldown=300) is False


def test_apply_cooldown_after_window_allows():
    from server.services.strategy.regime import apply_cooldown
    r1 = _make_regime(1, "R1", priority=10)
    r2 = _make_regime(2, "R2", priority=20)
    # 切换时刻 1000, now=1400 (差 400s > 300) → 允许
    assert apply_cooldown(r1, r2, last_switch_ts=1000.0, now_ts=1400.0, cooldown=300) is True


def test_apply_cooldown_no_history_allows():
    """last_switch_ts=None 表示首次切换，无历史 → 允许"""
    from server.services.strategy.regime import apply_cooldown
    r1 = _make_regime(1, "R1", priority=10)
    r2 = _make_regime(2, "R2", priority=20)
    assert apply_cooldown(r1, r2, last_switch_ts=None, now_ts=1000.0) is True


# ─────────────── Smoke ───────────────


def test_smoke_imports():
    from server.services.strategy.regime import match_regime, apply_cooldown, COOLDOWN_SECONDS
    assert COOLDOWN_SECONDS == 300