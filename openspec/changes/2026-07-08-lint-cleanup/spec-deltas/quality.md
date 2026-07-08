# Spec Delta — Quality / Lint

## REQ-QUAL-001: Lint 必须零错误

> **新增** REQ。

The codebase SHALL pass `ruff check server/ ...` with **zero errors** for the rules:
- F401, F841, E402, E712, E702, F541

The codebase SHALL preserve **all existing public re-exports** in `__init__.py` files (e.g., `from server.enums.trading import PriceType as PriceType`) so external imports continue to work.

### Scenario: clean lint

- **Given** all commits in change `2026-07-08-lint-cleanup` are applied
- **When** `ruff check server/ --select F401,F841,E402,E712,E702,F541` runs
- **Then** exit code 0 with "All checks passed"

### Scenario: backend still imports after cleanup

- **Given** all lint fixes applied
- **When** `python3 -c "from server.main import app"`
- **Then** no `ImportError` raised

### Scenario: re-exports still resolve

- **Given** `__init__.py` lint fixes use `as X` explicit re-exports
- **When** `from server.enums import PriceType, OrderType, Direction`
- **Then** all three names resolve

## REQ-QUAL-002: 禁用 / 抑制规则

> **新增** REQ。

- `noqa` comments SHALL NOT be used to silence lint errors in newly committed code (legacy `noqa` may remain until v20+ sweeps them).
- New code SHALL pass `ruff check` without suppression.

### Scenario: no new noqa introduced

- **Given** a commit to v19+
- **When** `git diff HEAD~1 | grep "^+.*noqa"`
- **Then** empty output (no new noqa)

## Modified Capabilities

None (this change is **code quality only**, no capability/spec change).