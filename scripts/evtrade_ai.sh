#!/usr/bin/env bash
# evtrade_ai.sh — AI 助手一行调 EvTrade REST 的薄壳 (wrapper)
#
# ⚠️ AI 助手入门口号: 这是你调 EvTrade 的唯一正确入口.
#    严禁拼 curl /api/auth/grant, 严禁 /api/auth/login (admin 密码外泄),
#    严禁 web_extract 拉 127.0.0.1, 严禁 execute_code 跑 subprocess 调接口.
#    2026-08-24 实测: 上面那些绕路 20+ 步才查到持仓, 本 wrapper 1 步搞定.
#
# Usage:
#   bash scripts/evtrade_ai.sh get  /api/auth/me
#   bash scripts/evtrade_ai.sh post /api/auth/heartbeat
#   bash scripts/evtrade_ai.sh post /api/orders/cancel '{"order_no":"..."}'
#   bash scripts/evtrade_ai.sh role=trader get /api/orders
#
# 对比 helper 直接调用 (scripts/evtrade_grant.py):
#   - 这层是 bash, 适合 shell + AI agent prompt 拼一行命令
#   - 内部实际调 evtrade_grant.py (授信 + Bearer + 401 重试 + cache 全在它里)
#
# 退出码: 0 = HTTP 2xx, 1 = HTTP 4xx/5xx, 2 = 参数错

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HELPER="${SCRIPT_DIR}/evtrade_grant.py"

# role 解析: role=trader 在第一个位置 → 转 env 传给 helper
ROLE_OPT=""
if [[ "${1:-}" == role=* ]]; then
    ROLE_OPT="EVTRADE_GRANT_ROLE=${1#role=}"
    export "${ROLE_OPT?}"
    shift
fi

if [[ $# -lt 2 ]]; then
    cat <<EOF
Usage:
  bash $0 [role=admin|trader] <get|post|put|patch|delete> <path> [json_body]

Examples:
  bash $0 get /api/auth/me
  bash $0 post /api/auth/heartbeat
  bash $0 post /api/orders/cancel '{"order_no":"..."}'
  bash $0 role=trader get /api/orders
EOF
    exit 2
fi

CMD="$1"
PATH_ARG="$2"
BODY="${3:-}"

if [[ ! -f "$HELPER" ]]; then
    echo "[ERR] helper not found: $HELPER" >&2
    exit 2
fi

# 透传给 helper. stderr 2>&1 进同一流, AI 看完整 trace
if [[ -n "$BODY" ]]; then
    python3 "$HELPER" "$CMD" "$PATH_ARG" "$BODY"
else
    python3 "$HELPER" "$CMD" "$PATH_ARG"
fi