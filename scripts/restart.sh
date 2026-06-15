#!/usr/bin/env bash
# EvTrade 一键启停 (Linux / git-bash)
# 用法:
#   ./scripts/restart.sh start     # 只启动
#   ./scripts/restart.sh stop      # 只停止
#   ./scripts/restart.sh restart   # 停 + 起 (默认)
#   ./scripts/restart.sh status    # 查看端口占用 + /api/health
#
# 约定端口:
#   8000  FastAPI uvicorn
#   50998 Vite dev server
#   8765  hqserver (WebSocket quotes)

set -euo pipefail

# ---- 路径 & 配置 -----------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$SCRIPT_DIR/.logs"
PID_DIR="$SCRIPT_DIR/.pids"
mkdir -p "$LOG_DIR" "$PID_DIR"

# Python 自动检测: 优先 venv，其次系统 python3/python
if [ -n "${VIRTUAL_ENV:-}" ]; then
    PYTHON="$VIRTUAL_ENV/bin/python"
elif [ -f "$ROOT_DIR/.venv/bin/python" ]; then
    PYTHON="$ROOT_DIR/.venv/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
elif command -v python &>/dev/null; then
    PYTHON="python"
else
    echo "ERROR: python not found" >&2
    exit 1
fi

BACKEND_PORT="${EVTRADE_API_PORT:-8000}"
FRONTEND_PORT="${EVTRADE_FRONTEND_PORT:-50998}"
HQSERVER_PORT=8765

# pid 文件
BACKEND_PID_FILE="$PID_DIR/backend.pid"
FRONTEND_PID_FILE="$PID_DIR/frontend.pid"
HQSERVER_PID_FILE="$PID_DIR/hqserver.pid"

# ---- 工具函数 --------------------------------------------------------------

_color() { printf '\033[%sm%s\033[0m' "$1" "$2"; }
info()  { echo "[$(date '+%H:%M:%S')] $(_color '1;34' '★') $*"; }
ok()    { echo "[$(date '+%H:%M:%S')] $(_color '1;32' '✓') $*"; }
warn()  { echo "[$(date '+%H:%M:%S')] $(_color '1;33' '!') $*" >&2; }
err()   { echo "[$(date '+%H:%M:%S')] $(_color '1;31' '✗') $*" >&2; }

pid_by_port() {
    local port="$1"
    ss -ltnH 2>/dev/null \
        | awk -v p=":$port" '$4 ~ p"$" {print $0}' \
        | head -1 \
        | awk '{print $NF}' \
        | grep -oE 'pid=[0-9]+' \
        | cut -d= -f2 \
        | head -1
    return 0
}

stop_pid() {
    local pid="$1" name="$2" wait_s="${3:-3}"
    if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
        return 0
    fi
    info "stop $name (pid=$pid) SIGTERM"
    kill -TERM "$pid" 2>/dev/null || true
    local i=0
    while kill -0 "$pid" 2>/dev/null && [ $i -lt $wait_s ]; do
        sleep 1; i=$((i+1))
    done
    if kill -0 "$pid" 2>/dev/null; then
        warn "$name 还在跑, SIGKILL"
        kill -KILL "$pid" 2>/dev/null || true
    fi
}

stop_by_pidfile() {
    local pf="$1" name="$2"
    if [ ! -f "$pf" ]; then
        return 0
    fi
    local pid
    pid="$(cat "$pf" 2>/dev/null || true)"
    if [ -n "$pid" ]; then
        stop_pid "$pid" "$name" 3
    fi
    rm -f "$pf"
}

kill_by_port() {
    local port="$1" name="$2"
    local pid
    pid="$(pid_by_port "$port")"
    if [ -n "$pid" ]; then
        warn "$name 端口 $port 仍被 pid=$pid 占用, 强杀"
        stop_pid "$pid" "$name" 2
    fi
}

health_check() {
    local url="http://127.0.0.1:$BACKEND_PORT/api/health"
    for i in 1 2 3 4 5 6 7 8 9 10; do
        if curl -sf -o /dev/null --max-time 1 "$url"; then
            ok "backend 健康 ($url)"
            return 0
        fi
        sleep 1
    done
    err "backend 健康检查失败: $url"
    return 1
}

# ---- 启停动作 --------------------------------------------------------------

stop_all() {
    info "=== STOP ==="
    stop_by_pidfile "$BACKEND_PID_FILE"   "backend"
    stop_by_pidfile "$FRONTEND_PID_FILE"  "frontend"
    stop_by_pidfile "$HQSERVER_PID_FILE"  "hqserver"
    kill_by_port "$BACKEND_PORT"  "backend"
    kill_by_port "$FRONTEND_PORT" "frontend"
    kill_by_port "$HQSERVER_PORT" "hqserver"
    pkill -TERM -f "uvicorn.*main:app"      2>/dev/null || true
    pkill -TERM -f "vite.*--port"            2>/dev/null || true
    pkill -TERM -f "python.*hqserver\.py"    2>/dev/null || true
    sleep 2
    pkill -KILL -f "uvicorn.*main:app"      2>/dev/null || true
    pkill -KILL -f "vite.*--port"            2>/dev/null || true
    pkill -KILL -f "python.*hqserver\.py"    2>/dev/null || true
    sleep 1
    local leftover=""
    [ -n "$(pid_by_port "$BACKEND_PORT")" ]  && leftover="$leftover :$BACKEND_PORT"
    [ -n "$(pid_by_port "$FRONTEND_PORT")" ] && leftover="$leftover :$FRONTEND_PORT"
    if [ -n "$leftover" ]; then
        err "端口未释放:$leftover — 请手动排查"
        return 1
    fi
    ok "已停止"
}

start_backend() {
    info "=== START backend (uvicorn :$BACKEND_PORT) ==="
    if [ -n "$(pid_by_port "$BACKEND_PORT")" ]; then
        warn "端口 $BACKEND_PORT 已被占用, 跳过启动"
        return 0
    fi
    cd "$ROOT_DIR/server"
    nohup "$PYTHON" -u -m uvicorn main:app \
        --host 0.0.0.0 --port "$BACKEND_PORT" \
        > "$LOG_DIR/backend.log" 2>&1 &
    local pid=$!
    echo "$pid" > "$BACKEND_PID_FILE"
    disown "$pid" 2>/dev/null || true
    cd "$ROOT_DIR"
    ok "backend 启动 (pid=$pid, log=$LOG_DIR/backend.log)"
}

start_frontend() {
    info "=== START frontend (vite :$FRONTEND_PORT) ==="
    local port_pid
    port_pid="$(pid_by_port "$FRONTEND_PORT")"
    if [ -n "$port_pid" ]; then
        # 端口被占：检查占用者 cmdline
        #   - 若是 vite/node/esbuild → 孤儿进程，强杀后让本函数继续启动
        #   - 否则 → 真的被别人占用，跳过并警告
        local cmdline
        cmdline="$(tr '\0' ' ' < /proc/"$port_pid"/cmdline 2>/dev/null || true)"
        if echo "$cmdline" | grep -qE 'vite|esbuild'; then
            warn "端口 $FRONTEND_PORT 被孤儿 vite 占用 (pid=$port_pid, cmd=$cmdline)，强杀后接管"
            stop_pid "$port_pid" "orphan-vite" 2
            sleep 1
            port_pid="$(pid_by_port "$FRONTEND_PORT")"
            if [ -n "$port_pid" ]; then
                err "强杀后端口仍被占, 跳过启动"
                return 1
            fi
        else
            warn "端口 $FRONTEND_PORT 被非 vite 进程占用 (pid=$port_pid, cmd=$cmdline)，跳过启动"
            return 0
        fi
    fi
    cd "$ROOT_DIR/client"
    # 严格端口（不让 vite 自己 fallback，否则 50998 被占就跑去 50999）
    nohup npx vite --host 0.0.0.0 --port "$FRONTEND_PORT" --strictPort \
        > "$LOG_DIR/frontend.log" 2>&1 &
    local pid=$!
    echo "$pid" > "$FRONTEND_PID_FILE"
    disown "$pid" 2>/dev/null || true
    cd "$ROOT_DIR"
    ok "frontend 启动 (pid=$pid, log=$LOG_DIR/frontend.log)"
}

start_hqserver() {
    info "=== START hqserver (ws :$HQSERVER_PORT) ==="
    if [ ! -d "$ROOT_DIR/hq" ]; then
        warn "hq/ 目录不存在, 跳过"
        return 0
    fi
    if pgrep -f "python.*hqserver\.py" >/dev/null; then
        warn "hqserver 已在跑, 跳过启动"
        return 0
    fi
    cd "$ROOT_DIR/hq"
    nohup "$PYTHON" -u hqserver.py \
        > "$LOG_DIR/hqserver.log" 2>&1 &
    local pid=$!
    echo "$pid" > "$HQSERVER_PID_FILE"
    disown "$pid" 2>/dev/null || true
    cd "$ROOT_DIR"
    ok "hqserver 启动 (pid=$pid, log=$LOG_DIR/hqserver.log)"
}

start_all() {
    start_backend
    start_frontend
    start_hqserver
    sleep 2
    health_check || warn "backend 健康检查失败, 但不阻塞"
}

show_status() {
    info "=== STATUS ==="
    echo "--- 端口 ---"
    ss -ltn 2>/dev/null | awk -v p="$BACKEND_PORT" -v f="$FRONTEND_PORT" -v h="$HQSERVER_PORT" '
        NR==1 || $4 ~ ":"p"$" || $4 ~ ":"f"$" || $4 ~ ":"h"$"'
    echo "--- pid 文件 ---"
    for f in "$BACKEND_PID_FILE" "$FRONTEND_PID_FILE" "$HQSERVER_PID_FILE"; do
        if [ -f "$f" ]; then
            local pid
            pid="$(cat "$f" 2>/dev/null || true)"
            if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
                ok "$(basename "$f") pid=$pid alive"
            else
                warn "$(basename "$f") pid=$pid dead"
            fi
        else
            echo "  $(basename "$f") missing"
        fi
    done
    echo "--- backend health ---"
    curl -sS --max-time 2 "http://127.0.0.1:$BACKEND_PORT/api/health" || true
    echo
}

# ---- 入口 ------------------------------------------------------------------

ACTION="${1:-restart}"
case "$ACTION" in
    start)   start_all ;;
    stop)    stop_all ;;
    restart) stop_all; sleep 1; start_all ;;
    status)  show_status ;;
    *) err "unknown action: $ACTION (use start|stop|restart|status)"; exit 2 ;;
esac
