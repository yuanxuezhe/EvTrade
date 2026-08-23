# Tasks — hermes serve 纳入 evctl 管理

## B1 后端工具：evctl.py 加 hermes 服务（默认启动）

- [x] `scripts/evctl.py`：
  - 常量 `HERMES_PORT = 9119`
  - `_hermes_cmd()`：`[shutil.which('hermes') or 'hermes', 'serve']`
  - `_hermes_preflight()`：`shutil.which('hermes')` 缺失 → 打印安装指引 + 返回 False
  - `_preflight_check()` 支持 callable 预检项（与 import 检查并存）
  - `SERVICES['hermes']` + 加入 `DEFAULT_SERVICES`
  - 模块 docstring Usage/约束更新（服务清单、9119 端口）

## B2 测试

- [x] evctl 新增逻辑单测（`_hermes_cmd` / `_hermes_preflight` / `_preflight_check` callable 分支）—— `scripts/` 不在 pytest 基线路径，测试放 `server/tests/` 或按需引入
- [x] 冒烟：`uv run python scripts/evctl.py status` 不 crash（本机无 hermes 时应正常显示 port free）

## B3 文档

- [x] `知识库/脚本工具/启停脚本.md`：服务表补 hermes 行（9119、外部 Hermes Agent、默认启动）、用法示例、修改指南
- [x] `scripts/README.md`：服务清单校准（原已过时，只列 3 服务）

## B4 归档

- [ ] spec-delta merge 到 `openspec/specs/dev-process-control/spec.md`
- [ ] mv change → `openspec/changes/archive/`
- [ ] 覆盖 ai-agent-panel「不纳入 evctl」决策的说明归档进 dev-process-control spec
