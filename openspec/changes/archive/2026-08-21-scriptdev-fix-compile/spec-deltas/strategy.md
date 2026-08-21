# Spec Deltas — Strategy（compile 端点契约）

> 追加于：`openspec/specs/strategy/spec.md` 末尾
> Change: 2026-08-21-scriptdev-fix-compile

---

### REQ-STRAT-021: Script 编译端点（2026-08-21）

The system SHALL provide `POST /api/script-strategy/scripts/{id}/compile` for static syntax validation of the script's Python code, without executing it or running any backtest.

#### Scenario: 编译语法正确

- **GIVEN** script id 存在且 code 字段可解析
- **WHEN** 客户端 POST `/api/script-strategy/scripts/{id}/compile`
- **THEN** 后端用 `ast.parse(code)` 静态校验
- **AND** 返 `200 {"ok": true, "warnings": []}`
- **AND** MUST NOT 修改 DB
- **AND** MUST NOT 调用回测引擎

#### Scenario: 编译语法错误

- **GIVEN** script id 存在但 code 含 Python 语法错误
- **WHEN** 客户端 POST 编译
- **THEN** `ast.parse` 抛 `SyntaxError`
- **AND** 后端捕获并返 `200 {"ok": false, "error": {"line": int, "col": int, "msg": str}}`
- **AND** `line` 为 1-based 错误行号；`col` 为 1-based 列偏移；`msg` 为 Python 原生错误信息

#### Scenario: script id 不存在

- **GIVEN** script id 在 DB 中不存在
- **WHEN** 客户端 POST 编译
- **THEN** 后端返 `404 {"code": "not_found", "msg": "script {id} not found"}`
- **AND** 前端 axios 拦截器弹错

#### Scenario: 未授权

- **GIVEN** user 未登录或 role 不足
- **WHEN** 客户端 POST 编译
- **THEN** 后端 MUST 返 `401` 或 `403`
- **AND** 公共脚本（`is_public=true`）可被任意登录用户编译（只读场景下也允许验证语法）