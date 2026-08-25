# dev-process-control delta

## MODIFIED Requirements

### Requirement: pytest testpaths 覆盖工作测试目录

The `pytest.ini` SHALL set `testpaths = server/tests tests`, ensuring the default `pytest` invocation at project root discovers the working tests in `server/tests/` (auth / push / services / test_place_async / test_v78_skip_rebroadcast / test_rpc_handlers / test_script_* / test_orders_cancel). The `tests/` directory at root continues to host integration scripts (`tests/strategy_exec/`, `tests/hq/`, `tests/client/`, root-level `test_quote_pattern_subscribe.py` / `test_quota_batch.py` / `stress_quota_5etf.py`).

#### Scenario: 默认 pytest 跑到 server/tests 工作测试

- **WHEN** developer runs `pytest` at project root
- **THEN** pytest collects tests from BOTH `server/tests/` (working tests) and `tests/` (integration / scripts)
- **AND** the legacy `tests/server/` subtree is removed entirely (it referenced deleted `server.models.orm` / `server.models.user` modules, no longer collected)

### Requirement: Ruff 作为默认 lint 工具

`pyproject.toml` SHALL include a `[tool.ruff]` section enforcing:
- `line-length = 120`（与 CLAUDE.md § 六 一致）
- `select = ["E", "F", "W"]`（pycodestyle 错误/警告 + pyflakes）
- `target-version = "py310"`（与 `.python-version` 一致）

The `.ruff_cache/` directory (already in repo) SHALL be the cache target.

#### Scenario: ruff check 0 错误

- **WHEN** developer runs `ruff check server/ hq/ iquant/ scripts/ conftest.py tests/`
- **THEN** exit code is 0; no rule violations reported

### Requirement: GitHub Actions CI workflow

A `.github/workflows/ci.yml` SHALL provide automated verification on push / pull_request to `master`:

- **`backend` job**: setup Python 3.10 + install uv → `uv sync` → `pytest hq/ server/tests/`
- **`frontend` job**: setup Node 20 → `cd client && npm ci` → `npm run build`

The CI SHALL NOT push artifacts or deploy. Cache SHALL be enabled for both pip and npm dependencies.

#### Scenario: push 触发 CI

- **WHEN** developer pushes a commit to `master`
- **THEN** GitHub Actions runs both `backend` and `frontend` jobs in parallel
- **AND** both must succeed before the commit can be merged