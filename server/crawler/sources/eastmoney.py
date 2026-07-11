"""
crawler/sources/eastmoney.py — 东方财富股票基础信息适配 (v23 slim-stocks-table)

数据源契约 (REQ-STOCK-005):
- 端点: https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax
- 参数: code=SZ000001 或 SH600519 (前缀+代码)
- 返回 JSON:
    {
      "jbzl": [{  # 基本资料 (28+ 字段)
        "SECUCODE": "000001.SZ",
        "SECURITY_NAME_ABBR": "平安银行",
        "INDUSTRYCSRC1": "金融业-货币金融服务",  # 申万一级
        "INDUSTRYCSRC2": "银行-国有大型银行",    # 申万二级
        ...
      }],
      "fxxg": [...]                              # 发行相关
    }

设计说明:
- push2.eastmoney.com (实时行情) 不被 Python requests 接受(只 curl 可),但
  emweb.securities.eastmoney.com (基本面查询) Python OK → 本适配用此端点
- v23 字段精简: 仅爬 stock_name + sector(申万二级),其余 9 字段不再入库
- 一次拉取返全部静态信息,无需多 endpoint

字段映射 (→ Stock ORM, v23 精简):
  SECURITY_NAME_ABBR → stock_name
  INDUSTRYCSRC2 → sector (申万二级)
  SECUCODE → stock_code (由 caller 传入,本函数不解析)
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
    """
    if "." in stock_code:
        # '000001.SZ' → market='SZ', code='000001'
        parts = stock_code.rsplit(".", 1)
        if len(parts) == 2:
            return f"{parts[1]}{parts[0]}"
    # 已经是 SZ000001 格式
    return stock_code


def fetch_base_info(stock_code: str, timeout: float = 10.0) -> Optional[Dict]:
    """从东方财富拉取单只股票基础信息(v23 仅 3 字段)

    Args:
        stock_code: 标准代码格式 "000001.SZ" 或 "600519.SH"
        timeout: HTTP 超时秒数

    Returns:
        标准 dict (Stock ORM 字段,v23 精简):
          {
            "stock_code": "000001.SZ",   # 由 caller 传入,这里冗余
            "stock_name": "平安银行",
            "sector": "银行-国有大型银行",  # 申万二级
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

        return {
            "stock_code": stock_code,
            "stock_name": jbzl.get("SECURITY_NAME_ABBR") or "",
            "sector": _extract_sector(jbzl.get("INDUSTRYCSRC2")),
        }
    except requests.exceptions.RequestException as e:
        print(f"[crawler.eastmoney] fetch_base_info {stock_code} failed: {e}")
        return None
    except (ValueError, KeyError) as e:
        print(f"[crawler.eastmoney] parse failed for {stock_code}: {e}")
        return None


# v23 移除:fetch_intro (intro 字段已删除)


# ---------- helpers ----------

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _html_to_text(html: str) -> str:
    """简单 HTML → 纯文本:去标签 + 折叠空白

    v23 保留:fetch_intro 引用此函数,但当前无业务调用方。保留以备未来。
    """
    if not html:
        return ""
    text = _HTML_TAG_RE.sub("", html)
    text = _WS_RE.sub(" ", text)
    return text.strip()


def _extract_sector(raw: Optional[str]) -> str:
    """申万二级 INDUSTRYCSRC2 直接入库 sector

    与 v21 的 _extract_industry (取 '-' 前段) 不同,v23 直接保留二级全名
    如 '银行-国有大型银行' 入库 sector,前端可直接筛选展示。
    """
    if not raw:
        return ""
    return raw.strip()