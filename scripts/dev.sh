#!/usr/bin/env bash
# 一键启停前后端服务（git-bash 包装）
# 用法：./scripts/dev.sh [start|stop|restart|status]

set -e
ACTION="${1:-start}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
powershell -NoProfile -ExecutionPolicy Bypass -File "$SCRIPT_DIR/dev.ps1" -Action "$ACTION"
