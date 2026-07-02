# Spec Delta — restructure-test-layout → dev-process-control

## MODIFIED Requirements

### Requirement: 测试目录布局约定（v10 新增，2026-07-02 restructure-test-layout）

The system MUST organize test files in a dedicated `tests/` directory that mirrors the source structure, separate pytest tests from manual scripts, and route runtime data files out of source directories.

#### Scenario S-DPC-008: 测试目录镜像源码结构

- **WHEN** developer 添加新 pytest 测试文件
- **THEN** MUST 放在 `tests/server/<mirror-path>/test_<module>.py`，mirror 路径 = 源码 `server/<path>/<module>.py` 去掉 `server/` 前缀
- **AND** 文件名规则 `test_<module>.py`，`<module>` = 被测模块名（不含 `.py`）
- **AND** import 风格统一 `from server.X import Y`（限定名），**禁止** `sys.path.insert + 裸名 import`
- **AND** pytest 测试文件 **必须** 在 `tests/server/` 下，**禁止** 混在 `server/<layer>/` 源码目录里

#### Scenario S-DPC-008 example

| 源码 | 测试 |
|---|---|
| `server/auth/security.py` | `tests/server/auth/test_security.py` |
| `server/api/orders/place.py` | `tests/server/api/orders/test_place.py` |
| `server/services/push/ord.py` | `tests/server/services/push/test_ord.py` |

#### Scenario S-DPC-008 违反示例（应拒收）

- **WHEN** developer 写 `server/test_security.py`（与源码同目录）
- **THEN** code review MUST 拒收
- **AND** `tests/server/test_security.py`（未按模块名 mirror）同样拒收
- **AND** `tests/server/auth/test_auth.py`（文件名误导：实际测的是 security.py）同样拒收

#### Scenario S-DPC-008: pytest 默认发现 server 测试

- **WHEN** developer run `pytest` 不带参数（项目根目录）
- **THEN** MUST 自动发现 `tests/server/` 下所有 `test_*.py` 并执行（前提：`pytest.ini` `testpaths` 含 `tests/server`）

#### Scenario S-DPC-008: 运行时数据文件不入源码目录

- **WHEN** 应用产生运行时数据文件（SQLite DB / 日志 / 缓存）
- **THEN** MUST 放 `data/` 子目录（与 `scripts/`、`docs/` 同级，repo 根下）
- **AND** `data/` 必须在 `.gitignore` 中（避免误提交用户本地数据）
- **AND** 启动配置（`config.py` / `settings.py`）的路径常量 MUST 指向 `data/`，**禁止** 指向 `server/<data-file>`
- **AND** 启动遇 `data/` 缺失 MUST 直接 fail，**禁止** fallback 到 `server/` 等其它位置

#### Scenario S-DPC-009: 测试分类（pytest vs manual vs integration）

- **WHEN** developer 添加新测试代码
- **THEN** 分类 MUST 明确：

| 类型 | 位置 | 运行方式 | 例子 |
|---|---|---|---|
| pytest 单元/集成测试 | `tests/server/<mirror>/test_*.py` | `pytest` 默认 collect | `test_security.py`, `test_db_session.py` |
| pytest 集成测试（需外部 broker/DB） | `tests/server/<mirror>/test_*.py` + `@pytest.mark.integration` | `pytest -m "not integration"` 默认 skip | `test_link.py` |
| 手测脚本（async debug / smoke） | `tests/manual/<name>.py` | `python tests/manual/<name>.py` | `test_rpc.py` |

- **AND** `pytest.ini` testpaths MUST 不含 `tests/manual/`（pytest 不 collect 手测脚本）
- **AND** 手测脚本允许用 `sys.path.insert`（独立运行，不依赖 pytest config）

#### Scenario S-DPC-009 违反示例（应拒收）

- **WHEN** developer 把手测脚本放在 `tests/server/`（被 pytest 误 collect，可能 hang 或 collect error）
- **THEN** code review MUST 拒收
- **AND** 集成测试不加 `@pytest.mark.integration`（CI 默认会跑，环境不具备会全失败）同样拒收
- **AND** 单元测试放 `tests/manual/`（需要手动跑，违反"pytest 默认全过"约定）同样拒收