"""
test_minute_bars_cache.py — minute_bars cache 集成单测 (change 2026-08-30-his-hq-cache-minute-bars)

覆盖:
  Case 1: query_minute_bars: 空 / 满 / 部分覆盖 / 跨段
  Case 2: upsert_minute_bars: 正常写入 / 重复 upsert 幂等 / 空 list 跳过
  Case 3: fetch_bars cache 集成:
    - 全覆盖 → 不调 broker (mock _fetch_one_chunk 失败如被调)
    - 部分覆盖 → 只调缺的段
    - 无覆盖 → 调全部段
    - cache 关闭 → 调全部段 (向后兼容)

策略:
  - query/upsert: mock _query_sync / _upsert_sync 测纯逻辑
  - fetch_bars 集成: patch query_minute_bars + _fetch_one_chunk, 验证调用次数和结果
"""
from unittest.mock import AsyncMock, patch
import pytest

from strategy_exec.market_data.hq_history import (
    HQHistoryClient,
    HQHistoryError,
    _chunk_fully_cached,
)


# ─────────────── Case 1: _chunk_fully_cached 纯函数 ───────────────


def test_chunk_fully_cached_empty():
    """空 cached → False"""
    assert _chunk_fully_cached([], "20250101", "20250110") is False


def test_chunk_fully_cached_full_weekday():
    """cached 覆盖整个 chunk (8 个工作日) → True"""
    # 20250101-20250110 含 8 个工作日:
    #   1-1 Wed, 1-2 Thu, 1-3 Fri, 1-4 Sat*, 1-5 Sun*, 1-6 Mon, 1-7 Tue, 1-8 Wed, 1-9 Thu, 1-10 Fri
    # cached 应有 8 天 (跳过 Sat/Sun)
    cached = [
        {"stime": f"{d}093100", "close": "100.0"}
        for d in ["20250101", "20250102", "20250103", "20250106", "20250107", "20250108", "20250109", "20250110"]
    ]
    assert _chunk_fully_cached(cached, "20250101", "20250110") is True


def test_chunk_fully_cached_missing_one_day():
    """cached 缺 1 天 → False"""
    cached = [
        {"stime": f"{d}093100", "close": "100.0"}
        for d in ["20250101", "20250102", "20250106", "20250107", "20250108", "20250109", "20250110"]
    ]
    # 缺 20250103 (周五)
    assert _chunk_fully_cached(cached, "20250101", "20250110") is False


def test_chunk_fully_cached_skips_weekend():
    """cached 只含工作日 (Sat/Sun 自动跳过) → True"""
    # 20250104 Sat + 20250105 Sun 不在 cached 也 OK
    cached = [
        {"stime": "20250101093100", "close": "100.0"},
        {"stime": "20250102093100", "close": "101.0"},
        {"stime": "20250103093100", "close": "102.0"},
        {"stime": "20250106093100", "close": "103.0"},  # Mon (跳过 Sat/Sun)
        {"stime": "20250107093100", "close": "104.0"},
        {"stime": "20250108093100", "close": "105.0"},
        {"stime": "20250109093100", "close": "106.0"},
        {"stime": "20250110093100", "close": "107.0"},
    ]
    assert _chunk_fully_cached(cached, "20250101", "20250110") is True


def test_chunk_fully_cached_single_day():
    """cached 单日 chunk → True"""
    cached = [{"stime": "20250101093100", "close": "100.0"}]
    assert _chunk_fully_cached(cached, "20250101", "20250101") is True


# ─────────────── Case 2: fetch_bars cache FULL HIT ───────────────


@pytest.mark.asyncio
async def test_fetch_bars_cache_full_hit_skips_broker():
    """cache FULL HIT → 不调 _fetch_one_chunk"""
    client = HQHistoryClient()

    # mock query_minute_bars 返 full cover bars (1m 数据)
    cached_bars = [
        {"stime": f"2025060{i}093100", "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05,
         "avg_price": 1.0, "volume": 1000}
        for i in range(3, 6)
    ]

    with patch(
        "strategy_exec.data_access.minute_bars.query_minute_bars",
        new=AsyncMock(return_value=cached_bars),
    ), patch.object(
        client, "_fetch_one_chunk", new=AsyncMock(side_effect=Exception("broker should not be called"))
    ), patch.object(client, "settings") as mock_settings:
        mock_settings.his_hq_cache_enabled = True
        mock_settings.his_hq_chunk_enabled = True
        mock_settings.his_hq_chunk_days = 10

        result = await client.fetch_bars("159992.SZ", "20250603", "20250605", "1d")

    assert len(result) == 3  # 3 个 1d K 线 (3 天)
    # 验证 _fetch_one_chunk 未被调用 (cache FULL HIT 跳 broker)
    # mock_fetch 没法直接 assert 没被调, 通过 patched Exception 副作用验证


# ─────────────── Case 3: fetch_bars cache MISS → broker all ───────────────


@pytest.mark.asyncio
async def test_fetch_bars_cache_miss_fetches_all_chunks():
    """cache MISS (cached 空) → broker 全部 chunk"""
    client = HQHistoryClient()

    broker_bars_per_chunk = [
        # chunk 1: 20250603-20250612
        [{"stime": "20250603093100", "close": "100.0"}],
        # chunk 2: 20250613-20250622
        [{"stime": "20250613093100", "close": "200.0"}],
        # chunk 3: 20250623-20250630
        [{"stime": "20250623093100", "close": "300.0"}],
    ]

    with patch(
        "strategy_exec.data_access.minute_bars.query_minute_bars",
        new=AsyncMock(return_value=[]),  # cache MISS
    ), patch(
        "strategy_exec.data_access.minute_bars.upsert_minute_bars",
        new=AsyncMock(return_value=1),
    ), patch.object(
        client, "_fetch_one_chunk",
        new=AsyncMock(side_effect=broker_bars_per_chunk),
    ) as mock_fetch, patch.object(client, "settings") as mock_settings:
        mock_settings.his_hq_cache_enabled = True
        mock_settings.his_hq_chunk_enabled = True
        mock_settings.his_hq_chunk_days = 10

        result = await client.fetch_bars("600519.SH", "20250603", "20250630", "1d")

    # 28 天 / chunk=10 → 3 chunks
    assert mock_fetch.call_count == 3
    assert len(result) >= 3  # 至少 3 个 1d


# ─────────────── Case 4: fetch_bars cache PARTIAL → 跳过完全覆盖 chunk ───────────────


@pytest.mark.asyncio
async def test_fetch_bars_cache_partial_skips_covered_chunks():
    """cache PARTIAL: cached 已覆盖的 chunk 不调 broker"""
    client = HQHistoryClient()

    # cached 覆盖 20250603-20250610 (8 天, 含 Sat/Sun = 6 工作日)
    # chunk 1 (20250603-20250612): 8 工作日 (1-3 Tue, 1-4 Wed, 1-5 Thu, 1-6 Fri, 1-9 Mon, 1-10 Tue, 1-11 Wed, 1-12 Thu)
    #    cached 缺 20250604/05/11/12 → broker 调
    # chunk 2 (20250613-20250622): cached 无 → broker
    # expected: broker 调用 2 次 (chunk 1 + chunk 2)
    cached_bars = [
        {"stime": f"2025060{i}093100", "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05,
         "avg_price": 1.0, "volume": 1000}
        for i in [3, 6, 7, 8, 9, 10]
    ]

    broker_bars = [{"stime": "20250620093100", "close": "200.0"}]

    with patch(
        "strategy_exec.data_access.minute_bars.query_minute_bars",
        new=AsyncMock(return_value=cached_bars),
    ), patch(
        "strategy_exec.data_access.minute_bars.upsert_minute_bars",
        new=AsyncMock(return_value=1),
    ), patch.object(
        client, "_fetch_one_chunk",
        new=AsyncMock(return_value=broker_bars),
    ) as mock_fetch, patch.object(client, "settings") as mock_settings:
        mock_settings.his_hq_cache_enabled = True
        mock_settings.his_hq_chunk_enabled = True
        mock_settings.his_hq_chunk_days = 10

        await client.fetch_bars("600519.SH", "20250603", "20250622", "1d")

    # 20 天 / chunk=10 → 2 chunks, chunk 1 部分覆盖 broker 调, chunk 2 broker 调
    assert mock_fetch.call_count == 2


# ─────────────── Case 5: cache 关闭 → 原 chunked 路径 ───────────────


@pytest.mark.asyncio
async def test_fetch_bars_cache_disabled_legacy_behavior():
    """cache 关闭 → 不查表, broker 全部"""
    client = HQHistoryClient()

    broker_bars = [{"stime": "20250603093100", "close": "100.0"}]

    with patch(
        "strategy_exec.data_access.minute_bars.query_minute_bars",
        new=AsyncMock(side_effect=AssertionError("should not query cache")),
    ), patch.object(
        client, "_fetch_one_chunk", new=AsyncMock(return_value=broker_bars),
    ) as mock_fetch, patch.object(client, "settings") as mock_settings:
        mock_settings.his_hq_cache_enabled = False
        mock_settings.his_hq_chunk_enabled = True
        mock_settings.his_hq_chunk_days = 10

        result = await client.fetch_bars("600519.SH", "20250603", "20250605", "1d")

    assert mock_fetch.call_count == 1


# ─────────────── Case 6: chunked fetch with cache 失败 → raise ───────────────


@pytest.mark.asyncio
async def test_fetch_bars_cache_partial_chunk_failure_raises():
    """cache PARTIAL: broker chunk 失败 → raise (不返 cached 已有数据)"""
    client = HQHistoryClient()

    cached_bars = [
        {"stime": "20250603093100", "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05,
         "avg_price": 1.0, "volume": 1000}
    ]

    with patch(
        "strategy_exec.data_access.minute_bars.query_minute_bars",
        new=AsyncMock(return_value=cached_bars),
    ), patch.object(
        client, "_fetch_one_chunk",
        new=AsyncMock(side_effect=HQHistoryError("broker timeout")),
    ), patch.object(client, "settings") as mock_settings:
        mock_settings.his_hq_cache_enabled = True
        mock_settings.his_hq_chunk_enabled = True
        mock_settings.his_hq_chunk_days = 10

        with pytest.raises(HQHistoryError, match="chunked fetch failed"):
            await client.fetch_bars("600519.SH", "20250603", "20250605", "1d")


# ─────────────── Case 7: is_full_cover 纯函数 ───────────────


def test_is_full_cover_full():
    """cached 覆盖 >= 50% 区间 → True"""
    from strategy_exec.data_access.minute_bars import is_full_cover
    # 20250101-20250110 含 8 个工作日
    cached = [{"stime": f"2025010{i}093100", "close": "100.0"} for i in [1, 2, 6, 7, 8, 9, 10]]
    assert is_full_cover(cached, "20250101", "20250110") is True


def test_is_full_cover_empty():
    """cached 空 → False"""
    from strategy_exec.data_access.minute_bars import is_full_cover
    assert is_full_cover([], "20250101", "20250110") is False


def test_is_full_cover_partial():
    """cached 只覆盖 50% 以下 → False"""
    from strategy_exec.data_access.minute_bars import is_full_cover
    cached = [{"stime": "20250101093100", "close": "100.0"}]
    assert is_full_cover(cached, "20250101", "20250130") is False