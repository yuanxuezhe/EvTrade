#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_schema_to_target.py — 把 dev 库的表结构同步到 prod 库 (v130+).

设计目标:
  解决"在 evtrade_dev 开发, 切到 evtrade 跑 → 表结构不一致 → 500"的根因.
  让 dev 库永远是 SoT, prod 库自动追上.

数据流:
  source (dev) ── export ──> schema.yml ── apply ──> target (prod)

调用:
  # 默认用 .env.dev (源) + .env.prod (目标)
  python scripts/sync_schema_to_target.py

  # 显式指定环境文件
  python scripts/sync_schema_to_target.py --dev-env .env.dev --prod-env .env.prod

  # Dry run: 只导 yml + diff, 不 apply
  python scripts/sync_schema_to_target.py --dry-run

  # Strict: 任何 drift 直接 fail (给 cron 用)
  python scripts/sync_schema_to_target.py --strict

工作流:
  1. 读 .env.dev → EVTRADE_DB_URL (源)
  2. 读 .env.prod → EVTRADE_DB_URL (目标, 当前进程用的)
  3. 临时切到源 URL, 跑 sync_schema.py export
  4. 切回目标 URL, 跑 sync_schema.py diff (dry-run 模式停在这里)
  5. 跑 sync_schema.py apply (把 yml → 目标库)
  6. 跑 sync_schema.py --strict 验收 (可选, --strict 时)

安全:
  - apply 只 ADD / CREATE / MODIFY, 不会 DROP. 物理上不可能破坏 prod 数据.
  - 列类型变更 (MODIFY) 可能锁表, 业务高峰期慎用, 建议低峰跑.
  - 推荐加 --strict 给 cron, 任何意外 drift 一票否决.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
SYNC_SCHEMA = HERE / "sync_schema.py"


def _read_env_file(env_path: Path) -> str:
    """读 .env 文件, 提取 EVTRADE_DB_URL. 没找到抛错."""
    if not env_path.exists():
        sys.exit(f"ERROR: {env_path} not found")
    with env_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == "EVTRADE_DB_URL":
                return v.strip().strip('"').strip("'")
    sys.exit(f"ERROR: EVTRADE_DB_URL not found in {env_path}")


def _run(args: list[str], env: dict | None = None, timeout: int = 300) -> int:
    """跑子命令, 透传 stdout, 返回 exit code."""
    print(f"\n$ {' '.join(args)}")
    r = subprocess.run(
        args,
        cwd=PROJECT_ROOT,
        env={**os.environ, **(env or {})},
        timeout=timeout,
    )
    return r.returncode


def main():
    ap = argparse.ArgumentParser(
        description="Sync schema from dev DB to prod DB (yml is the bridge)",
    )
    ap.add_argument("--dev-env", default="server/.env.dev", help="源 .env (默认 .env.dev)")
    ap.add_argument("--prod-env", default="server/.env.prod", help="目标 .env (默认 .env.prod)")
    ap.add_argument("--dry-run", action="store_true", help="只导 yml + diff, 不 apply")
    ap.add_argument("--strict", action="store_true", help="apply 用 --strict (任何 drift 拒绝)")
    ap.add_argument("--skip-verify", action="store_true", help="apply 后不跑 --strict 验收")
    args = ap.parse_args()

    dev_env = PROJECT_ROOT / args.dev_env
    prod_env = PROJECT_ROOT / args.prod_env
    dev_url = _read_env_file(dev_env)
    prod_url = _read_env_file(prod_env)

    print("=" * 60)
    print("  EvTrade schema sync: dev → prod (via yml)")
    print("=" * 60)
    print(f"  source (dev):  {dev_url.split('@')[-1]}")
    print(f"  target (prod): {prod_url.split('@')[-1]}")
    print(f"  yml:           server/schema.yml")
    print(f"  mode:          {'dry-run' if args.dry_run else 'strict' if args.strict else 'normal'}")
    print()

    # ── 1. Export: 源库 → yml ──
    print("[1/4] export source (dev) → schema.yml")
    if _run(
        [sys.executable, str(SYNC_SCHEMA), "export", "--source-url", dev_url],
        env={"EVTRADE_DB_URL": dev_url},
    ) != 0:
        sys.exit("export FAILED")

    # ── 2. Diff: yml ↔ 目标库 (dry-run 模式停这里) ──
    print("\n[2/4] diff schema.yml ↔ target (prod)")
    if _run(
        [sys.executable, str(SYNC_SCHEMA), "diff"],
        env={"EVTRADE_DB_URL": prod_url},
    ) != 0 and not args.dry_run:
        # diff 返回 0 也只是无 drift, 返回非 0 是有 drift — 都要继续, 除非 dry-run
        pass

    if args.dry_run:
        print("\n[dry-run] skip apply, exit 0")
        return

    # ── 3. Apply: yml → 目标库 ──
    apply_args = [sys.executable, str(SYNC_SCHEMA), "apply"]
    if args.strict:
        apply_args.append("--strict")
    print(f"\n[3/4] apply schema.yml → target (prod){' (--strict)' if args.strict else ''}")
    if _run(apply_args, env={"EVTRADE_DB_URL": prod_url}) != 0:
        sys.exit("apply FAILED")

    # ── 4. Verify: 跑 --strict 验收 (默认开, --skip-verify 跳过) ──
    if not args.skip_verify:
        print("\n[4/4] verify (--strict)")
        if _run(
            [sys.executable, str(SYNC_SCHEMA), "apply", "--strict"],
            env={"EVTRADE_DB_URL": prod_url},
        ) != 0:
            sys.exit("verify FAILED — apply 后仍有 drift, 手动排查")
        print("\n[OK] verify passed, prod schema fully matches dev")
    else:
        print("\n[4/4] verify skipped (--skip-verify)")

    print("\n" + "=" * 60)
    print("  DONE: dev schema → prod schema synced")
    print("=" * 60)


if __name__ == "__main__":
    main()
