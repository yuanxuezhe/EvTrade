# ai-agent delta

## MODIFIED Requirements

### Requirement: ai_analysis.py 模块结构规范

`server/api/ai_analysis.py` SHALL follow the project import-order convention:
1. Standard library imports grouped at top (`json`, `logging`, `os`, `subprocess`, `time`, `threading`, `asyncio`, `typing`)
2. Third-party imports next (`fastapi`, `pydantic`)
3. Local imports last (`server.*`)

The unused `import re` (line 36) SHALL be removed. The misplaced `import threading` (line 64, mid-file) SHALL be moved to the standard-library group at the top. The `_analysis_lock = threading.Lock()` instantiation SHALL remain at module-level so `subprocess.run` serializes across all in-flight requests.

#### Scenario: ai_analysis.py import 顺序

- **WHEN** developer opens `server/api/ai_analysis.py` lines 30-70
- **THEN** the stdlib group includes `threading`; `import re` is absent; `import threading` does NOT appear mid-file

### Requirement: ai_analysis 行为零变更

The change SHALL NOT modify any of:
- `POST /api/ai/ai-analysis` endpoint signature / request model / response model
- `_run_demo_script` / `_resolve_saved_json_path` / `_find_latest_report` / `_to_table_rows` helpers
- subprocess timeout / cwd / cmd / `_SUBPROCESS_TIMEOUT` value (240s)
- `_analysis_lock` lock semantics (process-serial)
- `/api/ai/status` endpoint behavior (added 2026-08-25)

Only the import-order / unused-import cleanup is applied.