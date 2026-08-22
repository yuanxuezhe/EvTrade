"""
crawler/sources/sina_list.py - 新浪 A 股全市场代码列表抓取

数据源契约 (REQ-STOCK-004):
- 端点: https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData
- 参数: node=hs_a (沪深京 A 股全市场)
       page=1..56
       num=100 (固定,新浪硬限)
       sort=symbol&asc=1 (按代码升序)
- 返回 JSON: Array[{
    "symbol": "sh600519",
    "name":   "贵州茅台",
  }]
- 实际总量: ~5560 只 (实测 page=1~56 有效,page=57+ 返 [])

代码转换 (新浪 -> EvTrade):
  sh600519  -> 600519.SH
  sz000001  -> 000001.SZ
  bj920169  -> 920169.BJ

缓存策略 (REQ-STOCK-004):
- 路径: data/all_a_codes.json (项目根 data/ 目录)
- 格式: {"fetched_at": "2026-07-12T11:30:00Z", "codes": ["600519.SH", ...]}
- TTL: 24 小时 (TTL_SINA_CACHE_HOURS)
- 失效条件: 文件不存在 / fetched_at 超过 TTL / JSON parse 失败
- 失败 = 抛异常,禁止 silent fallback (用户硬性偏好 #6)

性能:
- 56 次 HTTP 请求,每次 ~0.3s,合计 ~17s 拉全
- 缓存命中: <100ms 读 JSON

公开 API:
  fetch_all_a_codes(use_cache=True) -> List[str]
  clear_cache() -> None  # 测试用
  _fetch_one_page(page) -> List[dict]  # 内部
  _symbol_to_evtrade(sina_symbol) -> str  # 内部
"""
import json
import logging
import os
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# --- 配置常量 ---
SINA_HQ_URL = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
SINA_HQ_PAGE_SIZE = 100
SINA_HQ_NODE = "hs_a"
SINA_HQ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (EvTrade sync; +https://github.com/yuanxuezhe/EvTrade)",
    "Referer": "https://vip.stock.finance.sina.com.cn/",
}
CACHE_FILENAME = "all_a_codes.json"
CACHE_TTL_HOURS = 24
REQUEST_TIMEOUT_SEC = 10
PAGE_FETCH_INTERVAL_SEC = 0.05  # 50ms 间隔,避免对新浪过压


# --- 公共 API ---
def fetch_all_a_codes(
    use_cache: bool = True,
    cache_dir: str = "data",
    cache_ttl_hours: int = CACHE_TTL_HOURS,
) -> List[str]:
    """拉取沪深京 A 股全市场代码列表,带本地缓存。

    Args:
        use_cache: 是否优先用缓存(默认 True)。False = 强制重新拉。
        cache_dir: 缓存目录(相对项目根)
        cache_ttl_hours: 缓存 TTL(小时)

    Returns:
        去重排序后的 EvTrade 风格代码列表,例 ['000001.SZ', '600519.SH', ...]

    Raises:
        RuntimeError: sina 接口失败或缓存损坏(禁止 silent fallback)
    """
    if use_cache:
        cached = _read_cache(cache_dir, cache_ttl_hours)
        if cached is not None:
            logger.info("sina_list cache hit, codes=%d", len(cached))
            return cached

    logger.info("sina_list cache miss, fetching from sina...")
    raw_list = _fetch_all_pages()
    codes = sorted({_symbol_to_evtrade(r["symbol"]) for r in raw_list})
    logger.info("sina_list fetched codes=%d", len(codes))

    # 写缓存(不阻塞主流程,失败仅 warning)
    try:
        _write_cache(cache_dir, codes)
    except OSError as exc:
        logger.warning("sina_list cache write failed: %s (codes still returned)", exc)

    return codes


def clear_cache(cache_dir: str = "data") -> None:
    """删除缓存文件(测试用)"""
    cache_path = Path(cache_dir) / CACHE_FILENAME
    if cache_path.exists():
        cache_path.unlink()
        logger.info("sina_list cache cleared: %s", cache_path)


# --- 内部 ---
def _fetch_all_pages() -> List[dict]:
    """56 次分页拉 sina 接口,直到 page 返空数组"""
    all_rows: List[dict] = []
    page = 1
    while True:
        rows = _fetch_one_page(page)
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < SINA_HQ_PAGE_SIZE:
            # 最后不满一页(== 已无更多)
            break
        page += 1
        time.sleep(PAGE_FETCH_INTERVAL_SEC)
        if page > 100:
            # 防呆:超过 100 页强制退出
            logger.warning("sina_list hit page=100 safety limit, stop")
            break
    return all_rows


def _fetch_one_page(page: int) -> List[dict]:
    """拉 sina 单页,返 List[dict] (key 含 symbol/name)"""
    url = (
        f"{SINA_HQ_URL}?node={SINA_HQ_NODE}"
        f"&page={page}&num={SINA_HQ_PAGE_SIZE}"
        f"&sort=symbol&asc=1"
    )
    req = urllib.request.Request(url, headers=SINA_HQ_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SEC) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"sina fetch page={page} failed: {exc}") from exc

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"sina page={page} JSON parse failed: {exc}") from exc

    if not isinstance(data, list):
        raise RuntimeError(f"sina page={page} unexpected payload type: {type(data).__name__}")
    return data


def _symbol_to_evtrade(sina_symbol: str) -> str:
    """sh600519 -> 600519.SH ; bj920169 -> 920169.BJ ; sz000001 -> 000001.SZ"""
    if len(sina_symbol) < 8:
        raise ValueError(f"sina symbol too short: {sina_symbol!r}")
    market = sina_symbol[:2].upper()
    code = sina_symbol[2:8]
    if market not in ("SH", "SZ", "BJ"):
        raise ValueError(f"sina unknown market prefix: {sina_symbol!r}")
    return f"{code}.{market}"


def _cache_path(cache_dir: str) -> Path:
    return Path(cache_dir) / CACHE_FILENAME


def _read_cache(cache_dir: str, ttl_hours: int) -> Optional[List[str]]:
    """读缓存;失效返 None;损坏抛 RuntimeError"""
    path = _cache_path(cache_dir)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"sina_list cache corrupted ({path}): {exc}") from exc

    fetched_at_str = payload.get("fetched_at")
    codes = payload.get("codes")
    if not fetched_at_str or not isinstance(codes, list):
        raise RuntimeError(f"sina_list cache schema invalid ({path})")

    fetched_at = datetime.fromisoformat(fetched_at_str)
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - fetched_at
    if age > timedelta(hours=ttl_hours):
        logger.info("sina_list cache expired (age=%.1fh), will refetch", age.total_seconds() / 3600)
        return None

    return [str(c) for c in codes]


def _write_cache(cache_dir: str, codes: List[str]) -> None:
    """写缓存(含 fetched_at ISO timestamp)"""
    path = _cache_path(cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": SINA_HQ_URL,
        "count": len(codes),
        "codes": codes,
    }
    # 临时文件 + rename,防写一半损坏
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    tmp_path.replace(path)


# --- CLI 入口 (测试用) ---
if __name__ == "__main__":  # pragma: no cover
    import argparse
    parser = argparse.ArgumentParser(description="Fetch A-share codes from Sina")
    parser.add_argument("--no-cache", action="store_true", help="Force refetch, ignore cache")
    parser.add_argument("--clear-cache", action="store_true", help="Clear cache before fetching")
    args = parser.parse_args()

    if args.clear_cache:
        clear_cache()

    codes = fetch_all_a_codes(use_cache=not args.no_cache)
    print(f"total={len(codes)}")
    print("前 5:", codes[:5])
    print("后 5:", codes[-5:])
