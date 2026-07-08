# Tasks — v19 Lint Cleanup

## Phase 1: Setup

- [x] v17 auto-fix 67 F401 (commit `426266f`)
- [x] Proposal + spec delta written

## Phase 2: Per-module cleanup (按功能维度拆 5 commits)

- [ ] **Commit 1**: `core/api` cleanup
  - `server/api/users.py`: 2× E712 (`== True` → truthy)
  - `server/migrations/2026-07-06-add-orders-raw-id.py`: 1× F541 (f-string → plain string, auto-fixable)
  - 验证: `ruff check server/api/users.py server/migrations/`

- [ ] **Commit 2**: `re-exports` cleanup (22 F401, 单一目的)
  - `server/enums/__init__.py`: 3× F401 → `as PriceType, as OrderType, as Direction`
  - `server/services/t0/__init__.py`: 6× F401 → `as X` 显式 re-export
  - `server/utils/__init__.py`: 13× F401 → `as X`
  - 验证: `python3 -c "from server.enums import PriceType, OrderType, Direction; from server.services.t0 import get_fee_config, round_to_lot; from server.utils import format_db_dt"`

- [ ] **Commit 3**: `infra/rpc/repo` cleanup (8 fixes)
  - `server/rpc/client.py`: 5× E402 (import not at top — review 是否有循环依赖)
  - `server/repo/__init__.py`: 1× E402
  - `server/repo/system.py`: 1× E702 (`;` 多语句同行)
  - 验证: `python3 -c "from server.rpc.client import RpcClient; from server.repo import ..."` + WS push smoke

- [ ] **Commit 4**: `tests/strategy` cleanup (8 fixes)
  - `server/tests/strategy/test_engine.py`: 5× F841 + 1× E402
  - `server/tests/strategy/test_t0_endpoint_migration.py`: 2× F841
  - 验证: `pytest server/tests/strategy/test_engine.py server/tests/strategy/test_t0_endpoint_migration.py -x`

- [ ] **Commit 5**: `services/strategy/quote_consumer` cleanup (1 fix)
  - `server/services/strategy/quote_consumer.py`: 1× F841 (`all_strats` unused)
  - 验证: `ruff check server/services/strategy/quote_consumer.py`

## Phase 3: Verify

- [ ] 全量 `ruff check server/` exit 0
- [ ] `python3 -c "from server.main import app"` OK
- [ ] `pytest server/tests/strategy/` 75/75 PASS（实际可能更少，按文件）
- [ ] `/opsx:verify 2026-07-08-lint-cleanup` 调独立 subagent 验收

## Phase 4: Archive

- [ ] 5 commits 都 push 到 origin/master
- [ ] 调 `/opsx:archive 2026-07-08-lint-cleanup`
- [ ] 调 `/opsx:sync` 更新主 spec（如有 REQ-QUAL 新增）