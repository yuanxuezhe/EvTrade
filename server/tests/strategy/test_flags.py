"""
test_flags.py — 9-flag 注册表 + detect_flags 单测（task 4）

覆盖：
- FLAG_REGISTRY 9 项 + 字段齐 + 顺序
- get_flag_definitions 序列化顺序
- ma_bullish / ma_bearish 上升 / 下降序列触发
- ma_bullish 短 buffer (<20) 不触发
- rsi_overbought / rsi_oversold 单调序列触发
- vol_breakout 当根 vol ≥ 2× 平均
- vol_breakout 短 buffer 不触发
- price_change_up / price_change_down ±1%
- price_change_* prev_close=None 不触发
- macd_golden_cross / macd_death_cross V / Λ 型反转触发
- macd_cross 短 buffer 不触发
- detect_flags 返 Set[str]
"""


# ─────────────── Registry / Definitions ───────────────


def test_registry_has_9_entries():
    from server.services.strategy.flags import FLAG_REGISTRY
    assert len(FLAG_REGISTRY) == 9


def test_registry_codes_and_categories():
    from server.services.strategy.flags import FLAG_REGISTRY
    expected_codes = {
        "ma_bullish", "ma_bearish",
        "rsi_overbought", "rsi_oversold",
        "vol_breakout",
        "price_change_up", "price_change_down",
        "macd_golden_cross", "macd_death_cross",
    }
    assert set(FLAG_REGISTRY.keys()) == expected_codes

    categories = {fd.category for fd in FLAG_REGISTRY.values()}
    assert categories == {"trend", "oscillator", "volume", "momentum"}


def test_get_flag_definitions_returns_list_in_order():
    from server.services.strategy.flags import FLAG_REGISTRY, get_flag_definitions
    defs = get_flag_definitions()
    assert isinstance(defs, list)
    assert len(defs) == 9
    # 顺序与 FLAG_REGISTRY 一致
    for i, fd in enumerate(FLAG_REGISTRY.values()):
        assert defs[i] == {
            "code": fd.code, "name": fd.name,
            "category": fd.category, "description": fd.description,
        }


# ─────────────── MA flags ───────────────


def _make_buffer(prices, volumes=None):
    """构造 TickBuffer：每 tick 带 last_price + 可选 volume"""
    from server.services.strategy.indicators import TickBuffer
    b = TickBuffer()
    vols = volumes if volumes is not None else [100] * len(prices)
    for p, v in zip(prices, vols):
        b.append({"last_price": float(p), "volume": int(v)})
    return b


def test_ma_bullish_on_rising_series():
    from server.services.strategy.flags import detect_flags
    # 30 根稳步上涨 → MA5>MA10>MA20 必然成立
    prices = [10.0 + 0.5 * i for i in range(30)]
    active = detect_flags(_make_buffer(prices), prev_close=None)
    assert "ma_bullish" in active
    assert "ma_bearish" not in active


def test_ma_bearish_on_falling_series():
    from server.services.strategy.flags import detect_flags
    prices = [20.0 - 0.5 * i for i in range(30)]
    active = detect_flags(_make_buffer(prices), prev_close=None)
    assert "ma_bearish" in active
    assert "ma_bullish" not in active


def test_ma_no_fire_when_buffer_short():
    from server.services.strategy.flags import detect_flags
    # 只有 10 根，MA20 不足 → 不触发
    prices = [10.0 + 0.5 * i for i in range(10)]
    active = detect_flags(_make_buffer(prices), prev_close=None)
    assert "ma_bullish" not in active
    assert "ma_bearish" not in active


# ─────────────── RSI flags ───────────────


def test_rsi_overbought_on_monotonic_rise():
    from server.services.strategy.flags import detect_flags
    prices = [10.0 + i for i in range(15)]  # 单调涨
    active = detect_flags(_make_buffer(prices), prev_close=None)
    assert "rsi_overbought" in active


def test_rsi_oversold_on_monotonic_fall():
    from server.services.strategy.flags import detect_flags
    prices = [20.0 - i for i in range(15)]  # 单调跌
    active = detect_flags(_make_buffer(prices), prev_close=None)
    assert "rsi_oversold" in active


def test_rsi_no_fire_when_buffer_short():
    from server.services.strategy.flags import detect_flags
    # RSI(6) 至少 7 根；3 根不够
    prices = [10.0, 11.0, 12.0]
    active = detect_flags(_make_buffer(prices), prev_close=None)
    assert "rsi_overbought" not in active
    assert "rsi_oversold" not in active


# ─────────────── Vol flag ───────────────


def test_vol_breakout_when_vol_2x_average():
    from server.services.strategy.flags import detect_flags
    # 21 根：前 20 根 vol=100；最后 1 根 vol=300（3x 平均）
    vols = [100] * 20 + [300]
    prices = [10.0] * 21
    active = detect_flags(_make_buffer(prices, vols), prev_close=None)
    assert "vol_breakout" in active


def test_vol_no_breakout_when_vol_normal():
    from server.services.strategy.flags import detect_flags
    vols = [100] * 21  # 全平
    prices = [10.0] * 21
    active = detect_flags(_make_buffer(prices, vols), prev_close=None)
    assert "vol_breakout" not in active


def test_vol_no_fire_when_buffer_short():
    from server.services.strategy.flags import detect_flags
    vols = [100, 200]  # 不够 20+1
    prices = [10.0, 10.0]
    active = detect_flags(_make_buffer(prices, vols), prev_close=None)
    assert "vol_breakout" not in active


# ─────────────── Price change flags ───────────────


def test_price_change_up_when_last_up_1pct():
    from server.services.strategy.flags import detect_flags
    prices = [10.0] * 25
    active = detect_flags(_make_buffer(prices), prev_close=10.0)
    # last=10.0, prev_close=10.0 → change=0 → 不触发
    assert "price_change_up" not in active
    assert "price_change_down" not in active

    # 喂 last=11.0, prev_close=10.0 → +10% → 触发 up
    prices2 = [10.0] * 24 + [11.0]
    active2 = detect_flags(_make_buffer(prices2), prev_close=10.0)
    assert "price_change_up" in active2


def test_price_change_down_when_last_down_1pct():
    from server.services.strategy.flags import detect_flags
    prices = [10.0] * 24 + [9.0]
    active = detect_flags(_make_buffer(prices), prev_close=10.0)
    assert "price_change_down" in active


def test_price_change_no_fire_when_prev_close_missing():
    from server.services.strategy.flags import detect_flags
    prices = [10.0] * 24 + [20.0]  # last 翻倍
    active = detect_flags(_make_buffer(prices), prev_close=None)
    assert "price_change_up" not in active
    assert "price_change_down" not in active


# ─────────────── MACD cross flags ───────────────


def test_macd_golden_cross_on_sharp_reversal():
    from server.services.strategy.flags import detect_flags, IndicatorParams
    # 20 涨 + 8 跌 + 2 反弹：DIF 在跌势中下穿 DEA，末 2 根反弹触发金叉
    up1 = [10.0 + 0.3 * i for i in range(20)]      # 10.0 → 15.7
    down = [15.7 - 0.6 * i for i in range(8)]       # 15.7 → 11.3
    up2 = [11.3 + 0.4 * i for i in range(2)]        # 11.3 → 12.1
    prices = up1 + down + up2
    active = detect_flags(_make_buffer(prices), IndicatorParams.short_term())
    assert "macd_golden_cross" in active


def test_macd_death_cross_on_sharp_drop():
    from server.services.strategy.flags import detect_flags, IndicatorParams
    # 20 跌 + 8 涨 + 2 反弹下：DIF 上穿 DEA 后又下穿
    down1 = [20.0 - 0.3 * i for i in range(20)]
    up = [14.3 + 0.6 * i for i in range(8)]
    down2 = [19.1 - 0.4 * i for i in range(2)]
    prices = down1 + up + down2
    active = detect_flags(_make_buffer(prices), IndicatorParams.short_term())
    assert "macd_death_cross" in active


def test_macd_no_cross_when_buffer_too_short():
    from server.services.strategy.flags import detect_flags
    prices = [10.0, 11.0, 12.0]  # 不够 MACD 计算
    active = detect_flags(_make_buffer(prices))
    assert "macd_golden_cross" not in active
    assert "macd_death_cross" not in active


# ─────────────── detect_flags smoke ───────────────


def test_detect_flags_returns_set_type():
    from server.services.strategy.flags import detect_flags
    prices = [10.0 + 0.5 * i for i in range(30)]
    result = detect_flags(_make_buffer(prices))
    assert isinstance(result, set)
    # 所有元素必须是已注册的 flag code
    from server.services.strategy.flags import FLAG_REGISTRY
    for code in result:
        assert code in FLAG_REGISTRY


def test_detect_flags_custom_params_takes_effect():
    """传 short_term preset 后 flag 集合可不同（验证 params 真生效）"""
    from server.services.strategy.flags import detect_flags, IndicatorParams
    # 10 根单调上涨：standard 要 MA20 不够，short_term MA(3,6,10) 够
    prices = [10.0 + i for i in range(10)]
    active_std = detect_flags(_make_buffer(prices), IndicatorParams.standard())
    active_short = detect_flags(_make_buffer(prices), IndicatorParams.short_term())
    # standard MA20 不足 → ma_bullish 不在
    assert "ma_bullish" not in active_std
    # short_term MA10 满足 → ma_bullish 在
    assert "ma_bullish" in active_short