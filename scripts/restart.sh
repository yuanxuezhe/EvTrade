#!/usr/bin/env bash
# EvTrade 一键启停 (Linux 版)
# 用法:
#   ./scripts/restart.sh start     # 只启动 (端口已被占用则跳过)
#   ./scripts/restart.sh stop      # 只停止
#   ./scripts/restart.sh restart   # 停 + 起 (默认)
#   ./scripts/restart.sh status    # 查看端口占用 + /api/health
#
# 约定端口 (以运行现实为准，与 dev.ps1/README 不一致 — 8000/50998):
#   8000  FastAPI uvicorn
#   50998 Vite dev server
#   hqserver 不占端口，靠 pid 文件管理

set -euo pipefail

# ---- 路径 & 配置 -----------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$SCRIPT_DIR/.logs"
PID_DIR="$SCRIPT_DIR/.pids"
mkdir -p "$LOG_DIR" "$PID_DIR"

VENV_PY="/usr/local/lib/hermes-agent/venv/bin/python"
BACKEND_PORT="${EVTRADE_API_PORT:-8000}"
FRONTEND_PORT="${EVTRADE_FRONTEND_PORT:-50998}"

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

# 按端口找 PID (只看 LISTEN 套接字; 没找到返回空, 永远 exit 0)
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

# 优雅停: SIGTERM → 等 N 秒 → 还在就 SIGKILL
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

# 按 pid 文件停
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

# 按端口强杀 (兜底 — 应对 pid 文件丢失但进程还活着)
kill_by_port() {
    local port="$1" name="$2"
    local pid
    pid="$(pid_by_port "$port")"
    if [ -n "$pid" ]; then
        warn "$name 端口 $port 仍被 pid=$pid 占用, 强杀"
        stop_pid "$pid" "$name" 2
    fi
}

# 健康检查: HTTP GET /api/health
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
    # 1) 先按 pid 文件停
    stop_by_pidfile "$BACKEND_PID_FILE"   "backend"
    stop_by_pidfile "$FRONTEND_PID_FILE"  "frontend"
    stop_by_pidfile "$HQSERVER_PID_FILE"  "hqserver"
    # 2) 端口兜底 (针对 pid 文件丢失但进程还活着)
    kill_by_port "$BACKEND_PORT"  "backend"
    kill_by_port "$FRONTEND_PORT" "frontend"
    # 3) 进程名兜底 (uvicorn 有 reloader 时主进程/worker 各占一次端口,
    #    仅按端口查会漏掉 worker; 这里用命令行匹配一次清干净)
    pkill -TERM -f "uvicorn.*main:app"      2>/dev/null || true
    pkill -TERM -f "vite.*--port"            2>/dev/null || true
    pkill -TERM -f "python.*hqserver\.py"    2>/dev/null || true
    sleep 2
    pkill -KILL -f "uvicorn.*main:app"      2>/dev/null || true
    pkill -KILL -f "vite.*--port"            2>/dev/null || true
    pkill -KILL -f "python.*hqserver\.py"    2>/dev/null || true
    sleep 1
    # 4) 二次确认端口已释放
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
    # 端口已占 -> 跳过
    if [ -n "$(pid_by_port "$BACKEND_PORT")" ]; then
        warn "端口 $BACKEND_PORT 已被占用, 跳过启动"
        return 0
    fi
    cd "$ROOT_DIR/server"
    nohup "$VENV_PY" -u -m uvicorn main:app \
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
    if [ -n "$(pid_by_port "$FRONTEND_PORT")" ]; then
        warn "端口 $FRONTEND_PORT 已被占用, 跳过启动"
        return 0
    fi
    cd "$ROOT_DIR/client"
    nohup npx vite --host 0.0.0.0 --port "$FRONTEND_PORT" \
        > "$LOG_DIR/frontend.log" 2>&1 &
    local pid=$!
    echo "$pid" > "$FRONTEND_PID_FILE"
    disown "$pid" 2>/dev/null || true
    cd "$ROOT_DIR"
    ok "frontend 启动 (pid=$pid, log=$LOG_DIR/frontend.log)"
}

start_hqserver() {
    info "=== START hqserver ==="
    if pgrep -f "python.*hqserver\.py" >/dev/null; then
        warn "hqserver 已在跑, 跳过启动"
        return 0
    fi
    cd "$ROOT_DIR/hq"
    nohup "$VENV_PY" -u hqserver.py \
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
    ss -ltn 2>/dev/null | awk -v p="$BACKEND_PORT" -v f="$FRONTEND_PORT" '
        NR==1 || $4 ~ ":"p"$" || $4 ~ ":"f"$"'
    echo "--- pid 文件 ---"
    for f in "$BACKEND_PID_FILE" "$FRONTEND_PID_FILE" "$HQSERVER_PID_FILE"; do
        if [ -f "$f" ]; then
            local pid; pid="$(cat "$f")"
            if kill -0 "$pid" 2>/dev/null; then
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
