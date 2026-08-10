"""
2026-08-10-drop-mas-v1-params-from-code.py — DB 迁移脚本 (Phase 7 of `2026-08-10-strategy-params-sweep-best-live`)

目的:
    删除 mas_v1 demo 脚本 code 里的 `params = (...)` 块.
    v121+ 后 params 由 strategy_script.params_schema 唯一真源化, code 里再写
    `params = (...)` 会与 schema 比较, 反而触发 strict fail-fast.

执行:
    python3 server/migrations/2026-08-10-drop-mas-v1-params-from-code.py

幂等:
    - 跑前先读 code, 找 `    params = (` 标记
    - 找不到 → 已清理过, 跳过
    - 找到 → 正则删块 + UPDATE
    - 重复跑 → 二次跑读出已是新 code, 跳过 (幂等)

⚠️ BACKUP 提醒: 跑之前先 dump
    mysqldump -h 192.168.10.2 -P 33066 -u EvTrade -p evtrade strategy_script > backup_strategy_script_20260810.sql

设计: 不依赖 strategy_exec 包, 仅用 SQLAlchemy 跑 SQL
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "server"))

try:
    from dotenv import load_dotenv
    _ENV_PATH = os.path.join(os.path.dirname(HERE), ".env")
    if os.path.exists(_ENV_PATH):
        load_dotenv(_ENV_PATH, override=False)
except ImportError:
    pass

from sqlalchemy import text, create_engine

DATABASE_URL = os.environ.get("EVTRADE_DB_URL")
if not DATABASE_URL:
    raise RuntimeError("EVTRADE_DB_URL is required (v20 MySQL-only permanent standard).")
if not DATABASE_URL.startswith("mysql"):
    raise RuntimeError(f"Only MySQL is supported (v20 permanent standard). Got URL: {DATABASE_URL[:80]!r}")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


# 匹配 mas_v1 demo 的 params 块:
#     params = (
#         ("fast", 5),
#         ("slow", 20),
#         ("qty", 100),
#         ("rsi_period", 14),
#     )
# 4 个 4-space-indent 的 (`("key", val),`) 行 + 1 个 4-space 的 `)` 收尾
_PARAMS_BLOCK_RE = re.compile(
    r"    params = \(\n"          # 开头 `    params = (`
    r"(?:        \([^)]*\),\n)+"  # 至少一行 `        ("key", val),`
    r"    \)\n",                  # 收尾 `    )\n`
    re.MULTILINE,
)


def strip_params_block(code: str) -> str:
    """从 code 中移除 `params = (...)` 块.

    Args:
        code: 原始 user code (含 params 块)

    Returns:
        移除后的 code

    Raises:
        ValueError: 多于 1 个 params 块 (脚本异常, 不静默处理)
    """
    matches = list(_PARAMS_BLOCK_RE.finditer(code))
    if len(matches) == 0:
        return code  # 无块 (幂等跳过)
    if len(matches) > 1:
        raise ValueError(
            f"找到 {len(matches)} 个 params 块, 预期 1 个 — "
            f"脚本格式异常, 请手工检查"
        )
    # 删块 (含前面可能的前导空行, 但保留 indent)
    return _PARAMS_BLOCK_RE.sub("", code, count=1)


def main() -> None:
    db_label = DATABASE_URL.split("@")[-1] if DATABASE_URL else "NONE"
    print(f"[start] drop params block from mas_v1 (db={db_label})")

    with engine.begin() as conn:
        # ──── 步骤 1: 读 mas_v1 code ────
        print("\n[step 1] read mas_v1 code...")
        row = conn.execute(
            text("SELECT code, LENGTH(code) AS code_len FROM strategy_script "
                 "WHERE user_id = :u AND id = :i"),
            {"u": 6, "i": "mas_v1"},
        ).first()
        if row is None:
            print("  ⏭ mas_v1 不存在, 跳过 (demo 没被 seed 过?)")
            engine.dispose()
            return
        old_code, old_len = row[0], row[1]
        print(f"  current code_len={old_len}")

        # ──── 步骤 2: 检查是否有 params 块 ────
        if "    params = (" not in old_code:
            print("  ⏭ code 中无 '    params = (' 块, 已清理过, 跳过")
            engine.dispose()
            return

        # ──── 步骤 3: 删块 ────
        print("\n[step 2] strip params block...")
        new_code = strip_params_block(old_code)
        new_len = len(new_code)
        print(f"  new code_len={new_len} (delta={new_len - old_len})")

        # sanity check: 删后不应再含 `params = (` 块
        if "    params = (" in new_code:
            raise RuntimeError(
                "strip_params_block 后仍含 '    params = (' — "
                "正则未匹配干净, 回滚 (transaction 自动)"
            )

        # ──── 步骤 4: UPDATE ────
        print("\n[step 3] UPDATE strategy_script...")
        result = conn.execute(
            text("""
                UPDATE strategy_script
                   SET code = :c, updated_at = NOW()
                 WHERE user_id = :u AND id = :i
            """),
            {"c": new_code, "u": 6, "i": "mas_v1"},
        )
        print(f"  ✓ updated {result.rowcount} row(s)")

    # ──── 步骤 5: 验证 ────
    print("\n[verify] mas_v1 code 现在:")
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT LENGTH(code) AS code_len, code FROM strategy_script "
                 "WHERE user_id = :u AND id = :i"),
            {"u": 6, "i": "mas_v1"},
        ).first()
        if row:
            print(f"  code_len={row[0]}")
            # 打印前 600 字符看效果
            preview = row[1][:600]
            print("  --- 前 600 字符 ---")
            print(preview)
            print("  ---")

    engine.dispose()
    print("\n[OK] mas_v1 params 块删除完成")


if __name__ == "__main__":
    main()
