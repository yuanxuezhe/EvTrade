#!/usr/bin/env bash
# cleanup_logs.sh — 重启 EvTrade 栈前清日志,避免历史 log 干扰分析
#
# 用法:
#   ./scripts/cleanup_logs.sh           # 备份 (命名 N hours ago) 后清空
#   ./scripts/cleanup_logs.sh --hard    # 不备份直接清空
#
# 清哪些:
# - server/logs/*.log                  (backend server.log)
# - server/logs/*.jsonl                (quote_consumer_health.jsonl 等)
# - /tmp/backend*.log                  (我之前用 nohup 重定向的)
# - /tmp/mock_ticker.log
# - /tmp/hqserver*.log
# - /tmp/ws_subscribes.log

set -e

cd "$(dirname "$0")/.."

BACKUP_ROOT="/tmp/evtrade_log_backup_$(date +%Y%m%d_%H%M%S)"
HARD=0
[[ "${1:-}" == "--hard" ]] && HARD=1

archive() {
    local f="$1"
    [[ -f "$f" ]] || return 0
    if [[ $HARD -eq 1 ]]; then
        : > "$f"
    else
        mkdir -p "$BACKUP_ROOT"
        cp "$f" "$BACKUP_ROOT/$(echo "$f" | tr '/' '_')"
        : > "$f"
    fi
}

echo "=== 清 EvTrade 日志 (hard=$HARD) ==="

# Backend logs
for f in server/logs/*.log server/logs/*.jsonl; do
    [[ -f "$f" ]] && archive "$f" && echo "  ✓ $f"
done

# Hermes-managed nohup logs
for f in /tmp/backend*.log /tmp/mock_ticker.log /tmp/hqserver*.log /tmp/ws_subscribes.log; do
    [[ -f "$f" ]] && archive "$f" && echo "  ✓ $f"
done

if [[ $HARD -eq 0 ]]; then
    echo
    echo "备份: $BACKUP_ROOT"
else
    echo "(hard 模式: 无备份)"
fi
echo "=== 完成 ==="