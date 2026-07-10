"""
crawler/sources/eastmoney.py — 东方财富股票基础信息适配 (v21 stock-info-crawler)

数据源契约 (REQ-STOCK-005):
- 端点: https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax
- 参数: code=SZ000001 或 SH600519 (前缀+代码)
- 返回 JSON:
    {
      "jbzl": [{  # 基本资料 (28+ 字段)
        "SECUCODE": "000001.SZ",
        "SECURITY_NAME_ABBR": "平安银行",
        "INDUSTRYCSRC1": "金融业-货币金融服务",  # 申万一级
        "TRADE_MARKET": "深圳证券交易所",
        "REG_CAPITAL": "...",                    # 注册资本
        "ORG_PROFILE": "...",                    # 公司简介 (HTML)
        ...
      }],
      "fxxg": [...]                              # 发行相关
    }

设计说明:
- push2.eastmoney.com (实时行情) 不被 Python requests 接受(只 curl 可),但
  emweb.securities.eastmoney.com (基本面查询) Python OK → 本适配用此端点
- 公司简介 ORG_PROFILE 是 HTML,清洗成纯文本
- 一次拉取返全部静态信息,无需多 endpoint

字段映射 (→ Stock ORM):
  SECURITY_NAME_ABBR → stock_name
  INDUSTRYCSRC1 (申万一级) → industry
  INDUSTRYCSRC2 (申万二级,可选) → sector
  TRADE_MARKET → market
  REG_CAPITAL → 注册资本(字符串,暂不解析数值)
  ORG_PROFILE → intro (HTML → text)
  SECUCODE → stock_code
"""
import re
from typing import Optional, Dict

import requests


# 基础信息查询端点 (静态字段,Python reqs 可达)
_PAGE_AJAX_URL = "https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax"

# 反爬 headers
_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/Index",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def _format_code(stock_code: str) -> str:
    """000001.SZ → SZ000001(API 期望的 code 参数格式)

    注:东方财富的格式是 {market}{code} 不带点,如 SZ000001 / SH600519
    之前错把 '000001.SZ'.split('.', 1) 切成 ('000001', '.SZ')
    然后拼成 '000001.SZ'(market='000001', code='.SZ') 不变!

    正确做法:从右 split,或固定切前 6 位 + 后 2 位
    """
    if "." in stock_code:
        # '000001.SZ' → market='SZ', code='000001'
        parts = stock_code.rsplit(".", 1)
        if len(parts) == 2:
            return f"{parts[1]}{parts[0]}"
    # 已经是 SZ000001 格式
    return stock_code


def fetch_base_info(stock_code: str, timeout: float = 10.0) -> Optional[Dict]:
    """从东方财富拉取单只股票基础信息

    Args:
        stock_code: 标准代码格式 "000001.SZ" 或 "600519.SH"
        timeout: HTTP 超时秒数

    Returns:
        标准 dict (Stock ORM 字段):
          {
            "stock_code": "000001.SZ",
            "stock_name": "平安银行",
            "industry": "金融业-货币金融服务",     # 申万一级
            "sector": "...",                       # 申万二级 (可选)
            "market": "SZ",                        # 市场简称(从 stock_code 派生)
            "intro": "公司简介纯文本...",
          }
        None: 网络/反爬失败
    """
    code_param = _format_code(stock_code)
    try:
        resp = requests.get(
            _PAGE_AJAX_URL,
            params={"code": code_param},
            headers=_DEFAULT_HEADERS,
            timeout=timeout,
        )
        if resp.status_code != 200:
            print(f"[crawler.eastmoney] HTTP {resp.status_code} for {stock_code}")
            return None
        data = resp.json()
        jbzl_list = data.get("jbzl", [])
        if not jbzl_list:
            print(f"[crawler.eastmoney] empty jbzl for {stock_code}")
            return None
        jbzl = jbzl_list[0]

        # 解析 market: 从 SECUCODE "000001.SZ" 取 "SZ"
        secu = jbzl.get("SECUCODE") or stock_code
        market = secu.split(".")[-1] if "." in secu else ""

        # 公司简介 HTML → 纯文本
        intro_html = jbzl.get("ORG_PROFILE", "") or ""
        intro_text = _html_to_text(intro_html)

        return {
            "stock_code": stock_code,
            "stock_name": jbzl.get("SECURITY_NAME_ABBR") or "",
            "industry": _extract_industry(jbzl.get("INDUSTRYCSRC1")),
            "sector": _extract_industry(jbzl.get("INDUSTRYCSRC2")),  # 申万二级
            "market": market,
            "intro": intro_text[:4000] if intro_text else "",  # 限制长度
        }
    except requests.exceptions.RequestException as e:
        print(f"[crawler.eastmoney] fetch_base_info {stock_code} failed: {e}")
        return None
    except (ValueError, KeyError) as e:
        print(f"[crawler.eastmoney] parse failed for {stock_code}: {e}")
        return None


def fetch_intro(stock_code: str, timeout: float = 10.0) -> str:
    """单独拉公司简介(v21 兼容 API;fetch_base_info 已包含)

    Returns:
        纯文本公司介绍;失败返 ""
    """
    info = fetch_base_info(stock_code, timeout=timeout)
    return info.get("intro", "") if info else ""


# ---------- helpers ----------

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _html_to_text(html: str) -> str:
    """简单 HTML → 纯文本:去标签 + 折叠空白"""
    if not html:
        return ""
    text = _HTML_TAG_RE.sub("", html)
    text = _WS_RE.sub(" ", text)
    return text.strip()


def _extract_industry(raw: Optional[str]) -> str:
    """申万行业可能返 '金融业-货币金融服务' (一级-二级)
    本函数返一级部分 (用于 industry 字段)"""
    if not raw:
        return ""
    parts = raw.split("-")
    return parts[0].strip() if parts else raw.strip()