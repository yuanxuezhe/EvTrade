#!/bin/bash
# scripts/verify_change.sh - 收集验收证据包
# 用法: bash scripts/verify_change.sh <change-name> [base-ref]
# 例:   bash scripts/verify_change.sh 2026-07-08-t0-task-management main
# 输出: stdout 打 Evidence Pack，可被 verify slash command 捕获

set -u

CHANGE_NAME="${1:-}"
BASE_REF="${2:-main}"

if [ -z "$CHANGE_NAME" ]; then
  echo "ERROR: usage: $0 <change-name> [base-ref]" >&2
  exit 1
fi

# 项目根 = 脚本所在目录的父目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ARCHIVE_DIR="$PROJECT_ROOT/openspec/changes/archive/$CHANGE_NAME"

echo "=========================================="
echo "Evidence Pack for change: $CHANGE_NAME"
echo "Project root: $PROJECT_ROOT"
echo "Base ref: $BASE_REF"
echo "Archive dir: $ARCHIVE_DIR"
echo "Generated: $(date -Iseconds)"
echo "=========================================="

# --- 1. Git history ---
echo ""
echo "=== 1. Git history (base..HEAD) ==="
cd "$PROJECT_ROOT"
COMMITS=$(git log --oneline "$BASE_REF..HEAD" 2>/dev/null || git log --oneline -20)
echo "$COMMITS"
COMMIT_COUNT=$(echo "$COMMITS" | grep -c '^[0-9a-f]' || echo 0)
echo "--- commit count: $COMMIT_COUNT ---"

# --- 2. Archive structure ---
echo ""
echo "=== 2. Archive structure ==="
if [ -d "$ARCHIVE_DIR" ]; then
  ls -la "$ARCHIVE_DIR/"
  echo ""
  if [ -d "$ARCHIVE_DIR/spec-deltas" ]; then
    ls -la "$ARCHIVE_DIR/spec-deltas/"
  else
    echo "WARN: no spec-deltas directory"
  fi
else
  echo "ERROR: archive dir not found: $ARCHIVE_DIR"
  exit 1
fi

# --- 3. tasks.md completion ---
echo ""
echo "=== 3. tasks.md completion ==="
TASKS_FILE="$ARCHIVE_DIR/tasks.md"
if [ -f "$TASKS_FILE" ]; then
  DONE=$(grep -c '\[x\]' "$TASKS_FILE" || echo 0)
  TODO=$(grep -c '\[ \]' "$TASKS_FILE" || echo 0)
  echo "done: $DONE, todo: $TODO"
  if [ "$TODO" -gt 0 ]; then
    echo "--- remaining tasks ---"
    grep '\[ \]' "$TASKS_FILE"
  fi
else
  echo "ERROR: tasks.md not found"
fi

# --- 4. e2e scripts available ---
echo ""
echo "=== 4. e2e scripts available ==="
E2E_DIR="$PROJECT_ROOT/scripts/e2e"
if [ -d "$E2E_DIR" ]; then
  ls -la "$E2E_DIR/"
else
  echo "no e2e directory"
fi

# --- 5. backend health (best-effort) ---
echo ""
echo "=== 5. backend health ==="
HEALTH=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 http://localhost:8000/health 2>/dev/null || echo "000")
echo "HTTP $HEALTH"
if [ "$HEALTH" = "200" ]; then
  echo "--- /api/v1/t0-tasks/health (change-specific, if exists) ---"
  curl -s --max-time 3 http://localhost:8000/api/v1/t0-tasks/ 2>/dev/null | head -c 500
  echo ""
fi

# --- 6. commit stat per commit (line counts) ---
echo ""
echo "=== 6. per-commit stat ==="
for HASH in $(echo "$COMMITS" | awk '{print $1}'); do
  STAT=$(git show --stat --format='' "$HASH" 2>/dev/null | tail -1)
  FILES=$(git show --stat --format='' "$HASH" 2>/dev/null | grep '\|' | wc -l)
  echo "$HASH: $STAT (files: $FILES)"
done

# --- 7. delta spec REQ-IDs ---
echo ""
echo "=== 7. REQ-IDs in delta specs ==="
if [ -d "$ARCHIVE_DIR/spec-deltas" ]; then
  grep -hE 'REQ-[A-Z]+-[0-9]+' "$ARCHIVE_DIR/spec-deltas/"*.md 2>/dev/null | sort -u
fi

echo ""
echo "=========================================="
echo "Evidence Pack complete"
echo "=========================================="
