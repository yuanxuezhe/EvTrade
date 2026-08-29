"""
test_hq_history_chunked.py — chunked fetch 单测 (change 2026-08-30-his-hq-chunked-fetch)

覆盖:
  Case 1-5: _iter_chunks 纯函数 (5 cases)
  Case 6-7: chunked fetch 集成 (mock broker, 2 cases)
  Case 8: 任一段失败 → raise (不返部分数据)

策略:
  - _iter_chunks 纯函数测试, 无 IO
  - chunked fetch 集成: patch _fetch_one_chunk mock 返 bars, 验证拼凑 + sort + aggregator
  - 失败: patch _fetch_one_chunk 抛 HQHistoryError
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from unittest.mock import AsyncMock, patch
import pytest

from strategy_exec.market_data.hq_history import HQHistoryClient, HQHistoryError, _iter_chunks


# ─────────────── Case 1-5: _iter_chunks 纯函数 ───────────────


def test_iter_chunks_30day_chunk10():
    """30 天 / chunk=10 → 3 段 (1-10, 11-20, 21-30)"""
    chunks = _iter_chunks("20250101", "20250130", 10)
    assert chunks == [
        ("20250101", "20250110"),
        ("20250111", "20250120"),
        ("20250121", "20250130"),
    ]


def test_iter_chunks_31day_chunk10():
    """31 天 / chunk=10 → 4 段 (末段 1-1)"""
    chunks = _iter_chunks("20250101", "20250131", 10)
    assert chunks == [
        ("20250101", "20250110"),
        ("20250111", "20250120"),
        ("20250121", "20250130"),
        ("20250131", "20250131"),
    ]
    assert chunks[-1] == ("20250131", "20250131")  # 末段 1 天


def test_iter_chunks_single_day():
    """单日区间 (start==end) → 1 段"""
    chunks = _iter_chunks("20250101", "20250101", 10)
    assert chunks == [("20250101", "20250101")]


def test_iter_chunks_cross_year():
    """跨年 (20241201-20250131) / chunk=30 → 多段 (datetime 自动 rollover)"""
    chunks = _iter_chunks("20241201", "20250131", 30)
    assert len(chunks) >= 2
    # 第一段起点 = 20241201
    assert chunks[0][0] == "20241201"
    # 末段终点 = 20250131
    assert chunks[-1][1] == "20250131"
    # 验证每段 ≤ 30 天
    from datetime import datetime
    for s, e in chunks:
        d_s = datetime.strptime(s, "%Y%m%d")
        d_e = datetime.strptime(e, "%Y%m%d")
        assert (d_e - d_s).days + 1 <= 30


def test_iter_chunks_1year_37_chunks():
    """1 年 (20250101-20251231) / chunk=10 → 37 段 (365/10)"""
    chunks = _iter_chunks("20250101", "20251231", 10)
    assert len(chunks) == 37
    # 第一段起点 + 末段终点
    assert chunks[0] == ("20250101", "20250110")
    assert chunks[-1] == ("20251227", "20251231")
    # 验证 30+30+...+5 累加
    total_days = 0
    for s, e in chunks:
        from datetime import datetime
        d_s = datetime.strptime(s, "%Y%m%d")
        d_e = datetime.strptime(e, "%Y%m%d")
        total_days += (d_e - d_s).days + 1
    assert total_days == 365


def test_iter_chunks_empty_when_start_after_end():
    """start > end 返 []"""
    assert _iter_chunks("20250110", "20250101", 10) == []


# ─────────────── Case 6-7: chunked fetch 集成 (mock broker) ───────────────


@pytest.mark.asyncio
async def test_chunked_fetch_merges_and_sorts_bars():
    """chunked 开启: 2 段 mock broker, 拼凑 + sort by stime"""
    client = HQHistoryClient()

    # mock _fetch_one_chunk: 第 1 段返 3 根, 第 2 段返 3 根 (顺序乱)
    mock_bars_chunk1 = [
        {"stime": "20250102093100", "close": "100.0"},
        {"stime": "20250102093300", "close": "102.0"},
        {"stime": "20250102093200", "close": "101.0"},  # 乱序
    ]
    mock_bars_chunk2 = [
        {"stime": "20250115093100", "close": "200.0"},
        {"stime": "20250115093300", "close": "202.0"},
        {"stime": "20250115093200", "close": "201.0"},
    ]

    with patch.object(
        client, "_fetch_one_chunk", new=AsyncMock(side_effect=[mock_bars_chunk1, mock_bars_chunk2])
    ), patch.object(client, "settings") as mock_settings:
        mock_settings.his_hq_chunk_enabled = True
        mock_settings.his_hq_chunk_days = 10
        result = await client.fetch_bars("600519.SH", "20250102", "20250115", "1d")

    # 1d 聚合: 同日 09:31 / 09:32 / 09:33 都归 1-2 (1d) / 1-15 (1d) → 2 根
    assert len(result) == 2
    assert result[0]["stime"] == "20250102150000"  # 1-2 收盘
    assert result[0]["close"] == 102.0  # 1d close = 当日 1m 末根 (排序后)
    assert result[1]["stime"] == "20250115150000"  # 1-15 收盘
    assert result[1]["close"] == 202.0  # 1d close = 当日 1m 末根


@pytest.mark.asyncio
async def test_chunked_fetch_disabled_legacy_behavior():
    """chunked 关闭: 1 次全拉 (向后兼容)"""
    client = HQHistoryClient()

    mock_bars = [{"stime": "20250102093100", "close": "100.0"}]

    with patch.object(
        client, "_fetch_one_chunk", new=AsyncMock(return_value=mock_bars)
    ) as mock_fetch, patch.object(client, "settings") as mock_settings:
        mock_settings.his_hq_chunk_enabled = False
        mock_settings.his_hq_chunk_days = 10
        result = await client.fetch_bars("600519.SH", "20250101", "20250130", "1d")

    assert len(result) == 1
    # 1d 聚合 → 1 根 1d K 线
    assert mock_fetch.call_count == 1, "chunked 关闭应只调 1 次 broker"


# ─────────────── Case 8: 任一段失败 → raise ───────────────


@pytest.mark.asyncio
async def test_chunked_fetch_chunk_failure_raises():
    """第 2 段失败 → raise HQHistoryError (不返部分数据)"""
    client = HQHistoryClient()

    mock_chunk1 = [{"stime": "20250102093100", "close": "100.0"}]

    with patch.object(
        client, "_fetch_one_chunk",
        new=AsyncMock(side_effect=[mock_chunk1, HQHistoryError("broker timeout")])
    ), patch.object(client, "settings") as mock_settings:
        mock_settings.his_hq_chunk_enabled = True
        mock_settings.his_hq_chunk_days = 10
        with pytest.raises(HQHistoryError) as exc_info:
            await client.fetch_bars("600519.SH", "20250101", "20250130", "1d")
        # 错误信息含 chunk 信息
        assert "chunk 2/3" in str(exc_info.value) or "chunk 2/" in str(exc_info.value)
        assert "broker timeout" in str(exc_info.value)


# ─────────────── Case 9: 拼凑后 aggregator 集成 ───────────────


@pytest.mark.asyncio
async def test_chunked_fetch_aggregator_1d():
    """chunked 拼凑后调 aggregator (1d 跨周末跳过)"""
    client = HQHistoryClient()

    # 第 1 段 (1-1 ~ 1-3 含 1-4 Sat): 模拟 1-2 周四, 1-3 周五
    mock_chunk1 = [
        {"stime": "20250102093100", "close": "100.0"},
        {"stime": "20250102150000", "close": "105.0"},
        {"stime": "20250103093100", "close": "106.0"},
        {"stime": "20250103150000", "close": "110.0"},
    ]
    # 第 2 段 (1-4 ~ 1-15): 1-4 Sat, 1-5 Sun 跳过; 1-6 周一
    mock_chunk2 = [
        {"stime": "20250106093100", "close": "112.0"},
        {"stime": "20250106150000", "close": "118.0"},
    ]

    with patch.object(
        client, "_fetch_one_chunk", new=AsyncMock(side_effect=[mock_chunk1, mock_chunk2])
    ), patch.object(client, "settings") as mock_settings:
        mock_settings.his_hq_chunk_enabled = True
        mock_settings.his_hq_chunk_days = 5
        result = await client.fetch_bars("600519.SH", "20250101", "20250115", "1d")

    # 1d 聚合: 应 3 根 (1-2, 1-3, 1-6, 跳过 1-4 Sat / 1-5 Sun)
    assert len(result) == 3
    assert result[0]["stime"] == "20250102150000"
    assert result[1]["stime"] == "20250103150000"
    assert result[2]["stime"] == "20250106150000"