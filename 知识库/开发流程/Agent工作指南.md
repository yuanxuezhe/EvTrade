# Agent 工作指南 — 从分析到开发到测试的完整流程

> 本文件用于调教其他 Agent，使其在 EvTrade 项目中按统一规范工作。
> 核心原则：**知识库驱动开发、改动范围最小化、测试范围受控**。

---

## 一、项目背景速览

**EvTrade** 是一个 A 股智能交易终端，四服务架构：

| 服务 | 技术栈 | 端口 | 职责 |
|------|--------|------|------|
| 前端 | Vue 3 + Element Plus + ECharts + Pinia | :50998 | 交易终端 UI |
| 后端 | FastAPI + MySQL + RabbitMQ | :8000 | 交易核心、鉴权、WebSocket 推送 |
| 行情 | hqserver（Rust） | :8765 | 实时行情 FANOUT 推送 |
| 策略 | strategy_exec（Backtrader） | :8001 | 策略回测/实盘运行 |
| 柜台 | QMT / XtQuant | — | 下单/撤单/持仓/行情源 |
| 中间件 | RabbitMQ | — | msgpacket RPC + 信号推送 |

技术细节见 `知识库/项目总览.md`，这里不展开。

---

## 二、六条铁律（不可违反）

### 1. 知识库是唯一事实来源

`知识库/` 目录是项目的 Single Source of Truth。

- 每个知识库文档 ↔ 一组代码文件，一一对应
- 知识库描述"模块是什么、怎么实现的、改它要注意什么"
- **知识库过时 = 代码不可信**。发现不一致，当场修正

### 2. 先改知识库，再改代码

修改顺序不可颠倒：

```
定位知识库 → 改知识库 → 改代码 → 改测试 → git diff --stat 检查范围
```

先把"要怎么改"写进知识库，再按知识库的描述去改代码。

### 3. 改动范围最小化

只改知识库中描述到的模块对应的代码：

```
问自己三个问题：
1. 本次需求涉及哪些知识库文档？
2. 这些文档中「对应代码路径」列出了哪些文件？
3. 这些文件的改动会破坏哪些现有测试？

答案之外的一切文件，一律不碰。
```

禁止：顺手优化无关模块、大面积无关重构、跨模块一次性大改。

### 4. 测试范围受控

只为本次改动的模块写/改测试，跑测试时只跑涉及模块的文件。

| 改动类型 | 必跑测试 | 禁跑 |
|----------|----------|------|
| 后端某 API 模块 | `pytest server/tests/test_<模块>*.py` | 其他模块 |
| 数据表结构 | 相关表测试 + 引用该表的 API 测试 | 全量 |
| 前端页面 | 该页面对应的测试（如有） | 全量 |
| 策略服务 | `pytest strategy_exec/tests/` 相关文件 | 主服务测试 |
| 纯知识库改动 | 无需跑测试 | — |

### 5. 知识库文件规范

- 目录名、文件名一律**中文**
- 代码路径、函数名、变量名保留**英文原文**
- 单文件**不超过 300 行**，超过就拆
- 每个文档必含固定章节（见下文模板）

### 6. 禁止历史版本标注

- 代码注释、知识库文档**只写现状**，禁止 "vNN"、"YYYY-MM-DD 改动/fix" 这类历史叙事
- 纯历史注释删除；有技术实质的去掉版本/日期前缀保留内容
- 历史变化通过 **git 提交记录（中文）** 承载：按逻辑单元提交，`git log`/`git blame` 可追溯
- 例外：REQ-xxx 编号、openspec change 目录名（路径引用）、库名（pydantic v2）、协议版本（UUID v4）

---

## 三、分析阶段 — 理解项目与定位改动点

### 3.1 第一步：读知识库

拿到任何需求，先在 `知识库/` 中定位对应文档。用快速定位索引：

```
知识库/全局规范.md → 第六节「快速定位索引」
```

示例：

| 我要改… | 先读 |
|---------|------|
| 下单/撤单逻辑 | `后端服务/交易核心/下单与撤单.md` |
| T0 做T统计 | `后端服务/T0做T/` 下全部文档 |
| 策略脚本 | `后端服务/策略引擎/` + `策略服务/` |
| 前端页面 | `前端/页面/<页面名>.md` |
| 前端状态管理 | `前端/状态管理/<store 名>.md` |
| 数据库加字段 | `数据库/Schema说明.md` + 对应表文档 |

### 3.2 第二步：读源码

知识库给了方向，但要理解具体实现细节，必须读源码。

读源码的优先级：
1. 知识库文档「对应代码路径」章节列出的文件 — **必读**
2. 知识库文档「文件清单」表格中的文件 — **必读**
3. 知识库文档「依赖关系」章节提到的上下游模块 — **按需读**

### 3.3 第三步：梳理现状

读完知识库 + 源码后，能回答：
- 当前实现是什么？（数据流、函数调用链、状态流转）
- 要改的点在哪里？（具体到文件、函数、行号）
- 改动会影响哪些上下游模块？
- 哪些测试需要跑？

---

## 四、开发阶段 — 知识库驱动修改

### 4.1 先改知识库

把"要怎么改"先写进知识库文档。改的内容包括：
- 新增的接口、字段、页面、函数 — 写进「核心实现」章节
- 修改的流程 — 更新对应描述
- 新增的文件 — 补进「文件清单」表格
- 对应代码路径变化 — 更新「对应代码路径」章节

**知识库文档模板**（每个文件必须包含全部章节）：

```markdown
# <模块名>

## 对应代码路径
（相对项目根目录的路径列表，锚定可修改的文件范围）

## 功能概述
（一段话说清功能）

## 文件清单
| 代码文件 | 作用 |
|----------|------|

## 核心实现
### <子功能>
（详细到能按文档改代码：函数签名、参数、返回结构、状态码、
表字段、WS消息格式、HTTP路径与方法、边界条件）

## 依赖关系
- 上游：依赖哪些模块
- 下游：被哪些模块依赖

## 修改指南
（改动注意事项、牵连点、相关测试文件与运行命令）
```

### 4.2 再改代码

按知识库中已更新的描述，修改对应代码文件。代码路径必须与知识库文档中的「对应代码路径」一致。

**后端改动顺序**（自底向上）：
1. 数据层：`server/tables/` （如涉及表结构变化，先改 `schema.yml` → `gen_tables.py` → `sync_schema.py`）
2. 服务层：`server/services/` （业务逻辑）
3. API 层：`server/api/` （HTTP 端点，调用服务层）
4. 导出：`server/services/<模块>/__init__.py` （新增函数记得导出）

**前端改动顺序**（自底向上）：
1. API 层：`client/src/api/` （新增/修改 API 调用方法）
2. 状态管理：`client/src/stores/` （如有状态变化）
3. 页面/组件：`client/src/views/` 或 `client/src/components/` （UI 交互）

### 4.3 实战示例

**需求**：策略开发页面，点击"新建脚本"按钮直接在后端创建脚本并显示到列表，不再等用户手动保存。脚本名 `new_strategy`，重名则递增 `new_strategy01`、`02`。

**第一步：定位知识库**
```
知识库/后端服务/策略引擎/脚本策略模块.md  → 后端 script_strategy 模块
知识库/前端/页面/策略开发与运行.md       → 前端 ScriptDev.vue
```

**第二步：先改知识库**

在 `脚本策略模块.md` 的「核心实现」章节增加：
```
POST /scripts/new — 即时创建脚本
- 调用 auto_create_script(user_id)：自动命名 new_strategy → new_strategy01 → 02…
- 返回创建的 ScriptOut（含 id、name、code、params_schema）
```

在 `策略开发与运行.md` 更新新建流程描述：
```
点击"新建脚本" → 立即调 POST /scripts/new → 后端自动命名并创建
→ 前端刷新列表 + 选中新脚本 → 用户在编辑器中直接改
```

**第三步：再改代码**

后端（3 文件）：
- `server/services/script_strategy/scripts.py` — 新增 `auto_create_script()` 函数
- `server/api/script_strategy/scripts.py` — 新增 `POST /scripts/new` 端点
- `server/services/script_strategy/__init__.py` — 导出新函数

前端（2 文件）：
- `client/src/api/script_strategy.js` — 新增 `newScript()` 方法
- `client/src/views/ScriptDev.vue` — `onCreate()` 改为调 API + 刷新列表 + 选中

**第四步：改测试**（见下节）

**第五步：同步收尾**
```bash
git diff --stat   # 确认 7 文件改动，全部在 script_strategy 模块内
```

---

## 五、测试阶段 — 范围受控的验证

### 5.1 写测试

只为本次改动的模块写测试。测试文件放在对应位置：
- 后端：`server/tests/test_<模块>_<功能>.py` 或 `tests/server/<模块>/`
- 前端：`tests/` 下对应目录
- 策略服务：`strategy_exec/tests/`

测试用例覆盖：
1. **正常路径** — 核心功能能跑通
2. **边界条件** — 递增、重名、空值等
3. **权限校验** — 未认证返回 401 等
4. **回归检查** — 已有功能没被改坏

### 5.2 跑测试

```bash
# 只跑涉及模块的测试
E:/EvTrade/.venv/Scripts/python.exe -m pytest server/tests/test_script_new.py -v
E:/EvTrade/.venv/Scripts/python.exe -m pytest server/tests/test_script_strategy_compile.py -v
```

**pytest 运行须知**：
- 项目使用 `pytest.ini` 配置，`conftest.py` 中有 PYTEST_CURRENT_TEST 检测
- pytest 模式下自动跳过 RPC 连接和 WS 启动（不需要真实 RabbitMQ/MySQL）
- 用项目 `.venv` 的 Python：`E:/EvTrade/.venv/Scripts/python.exe`
- 不要跑全量测试浪费时间

### 5.3 实战示例（续上一节）

新增测试文件 `server/tests/test_script_new.py`，4 个用例：

```python
def test_new_script_first(client, auth_header):
    """首次创建 → 名为 new_strategy"""

def test_new_script_increment_01(client, auth_header):
    """已存在 new_strategy → 创建 new_strategy01"""

def test_new_script_increment_02(client, auth_header):
    """已存在 new_strategy + 01 → 创建 new_strategy02"""

def test_new_script_unauthorized(client):
    """未认证 → 401"""
```

跑测试：
```bash
$ python -m pytest server/tests/test_script_new.py server/tests/test_script_strategy_compile.py -v
# 4 passed + 3 passed = 7 passed
```

回归确认：
```bash
$ python -m pytest tests/server/strategy/test_strategy_v123_api.py -v
# 6 passed — 原有功能未被破坏
```

---

## 六、收尾阶段 — 同步与验证

### 6.1 git diff --stat 检查范围

```bash
git diff --stat
git status --short
```

检查点：
- 改动的文件是否全部在本次需求涉及的模块内？
- 有没有顺手改了无关文件？
- 有没有忘记提交的知识库改动？

### 6.2 知识库-代码一致性检查

- 知识库「对应代码路径」列出的文件 = 实际改动的文件？
- 知识库「核心实现」描述的逻辑 = 代码实际实现的逻辑？
- 新增的函数/接口是否已写入知识库？

### 6.3 更新工作日志

在 `E:\EvTrade\.workbuddy\memory\YYYY-MM-DD.md` 追加：
- 做了什么（一句话）
- 改了哪些文件（知识库 + 代码 + 测试，分列）
- 测试结果
- git diff --stat 确认范围

---

## 七、常见陷阱与避坑指南

### 7.1 忘记导出新函数

在 `server/services/<模块>/__init__.py` 中导出新函数，否则 API 层 import 会失败。

**症状**：`ImportError: cannot import name 'auto_create_script'`

**修复**：在 `__init__.py` 的 import 列表和 `__all__` 列表中加入新函数。

### 7.2 撤单端点 HTTP 方法

FastAPI 中 `@router.delete("/{order_no}")` 对应 `DELETE` 方法，不是 `POST`。
写知识库时要核实实际的 HTTP 方法，不要想当然。

### 7.3 前端 el-table 数组更新

不要整体替换 `form.value.params_schema = newArr`，会导致 Vue patch 报错。
用 `splice` 保持引用：`form.value.params_schema.splice(0, len, ...newArr)`。

### 7.4 测试中的 PYTEST_CURRENT_TEST

pytest 模式下 `conftest.py` 会检测 `PYTEST_CURRENT_TEST` 环境变量，自动跳过 RPC/WS 启动。
测试不需要真实的 RabbitMQ 或 MySQL 数据库。

### 7.5 strategy_exec 的 stale task 清理

设计文档中提到 `progress > 5min` 的 stale task 自动标记 failed，但实际代码中可能仅有注释，
没有真正实现。知识库要如实标注，不要脑补。

### 7.6 子代理前端任务可能被中断

如果用子代理（Agent）并行写知识库，前端任务可能因内容过大被中断。
策略：前端部分自己直接读源码写，或拆成更小的子任务。

---

## 八、工作流程总览图

```
┌─────────────────────────────────────────────────────────────────┐
│                        收到用户需求                              │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
                ┌─────────────────────┐
                │  1. 定位知识库文档    │  读 知识库/全局规范.md 快速定位索引
                │     读文档 + 读源码   │  理解当前实现
                └──────────┬──────────┘
                           │
                           ▼
                ┌─────────────────────┐
                │  2. 先改知识库        │  更新核心实现、文件清单、对应代码路径
                │     （强约束）        │  涉及多个模块则每份都改
                └──────────┬──────────┘
                           │
                           ▼
                ┌─────────────────────┐
                │  3. 再改代码          │  后端: tables → services → api
                │     按知识库描述       │  前端: api → stores → views
                └──────────┬──────────┘
                           │
                           ▼
                ┌─────────────────────┐
                │  4. 只测涉及模块      │  写针对性测试 + 跑涉及模块的回归
                │     禁全量            │  用 .venv 的 python 跑 pytest
                └──────────┬──────────┘
                           │
                           ▼
                ┌─────────────────────┐
                │  5. git diff --stat  │  确认改动范围最小化
                │     检查范围          │  无无关文件、无遗漏知识库改动
                └──────────┬──────────┘
                           │
                           ▼
                ┌─────────────────────┐
                │  6. 更新工作日志      │  .workbuddy/memory/YYYY-MM-DD.md
                └─────────────────────┘
```

---

## 九、关键路径速查表

| 资源 | 路径 |
|------|------|
| 全局规范 | `知识库/全局规范.md` |
| 目录索引 | `知识库/目录索引.md` |
| 项目总览 | `知识库/项目总览.md` |
| 后端入口 | `server/main.py` |
| 后端配置 | `server/config.py` |
| 数据库 Schema | `server/schema.yml` |
| 启停脚本 | `scripts/evctl.py` |
| pytest 配置 | `pytest.ini` + `conftest.py` |
| 项目 venv | `E:/EvTrade/.venv/Scripts/python.exe` |
| 工作日志 | `.workbuddy/memory/YYYY-MM-DD.md` |
| 长期记忆 | `.workbuddy/memory/MEMORY.md` |

---

## 十、Agent 自检清单

每次任务完成后，逐项确认：

- [ ] 知识库文档已先于代码更新？
- [ ] 知识库「对应代码路径」与实际改动的文件一致？
- [ ] 没有改动知识库未描述的模块？
- [ ] 测试只跑了涉及模块的文件？
- [ ] 新增函数已在 `__init__.py` 导出？
- [ ] `git diff --stat` 确认范围最小化？
- [ ] 工作日志已更新？

全部打勾，任务才算完成。

---

## 十一、AI 助手 skill 速查表（2026-08-27 瘦身）

> **2026-08-27 末态：EvTrade 项目 0 个专属 skill**。39 个全部 archive（137 个总 archive），
> 用法写在 `scripts/evtrade_cli/` + `知识库/脚本工具/evtrade-cli.md` + 各业务模块 spec.md。
> 遇到 EvTrade 相关问题，**先查知识库 + 脚本目录**，按下面速查表定位。

### A. 业务场景速查（最常用）

| 场景 | 看这里 | 跑这个 |
|------|--------|--------|
| 起停服务 / 看健康状态 / 重启 | `知识库/脚本工具/启停脚本.md` | `scripts/evctl.py status\|restart <svc>` |
| 调 EvTrade 后端 API（下单/查持仓/订阅WS） | `知识库/脚本工具/evtrade-cli.md` | `scripts/evtrade_cli/ev_login.py` + ev_api.py + ev_ws.py |
| DB schema 漂移 / 加列 | `知识库/脚本工具/数据库迁移与Schema.md` | `scripts/sync_schema.py export/diff/apply` |
| broker push 字段对不上 | `知识库/后端服务/RPC通信/` | 读 `server/services/push/*.py` |
| 持仓没刷新 / pos_push 不通 | `知识库/后端服务/数据同步/` | `server/services/push/pos.py` |
| RPC 健康灯不亮 / 503 | `知识库/后端服务/RPC通信/` | `server/services/rpc_health.py` |
| WS 推送收不到 | `知识库/后端服务/WebSocket推送/` | `server/ws/manager.py` |
| 下单/撤单 服务端 | `知识库/后端服务/交易核心/` | `server/api/orders/` |
| T0 / 当日盈亏算错 | `知识库/后端服务/T0做T/` | `server/services/t0/aggregators.py` |
| 前端某列不更新 | `client/src/utils/format.js` STATUS_LABEL/RANK | 读 store reactivity 设计 |
| ETF 价格丢 0 | `client/src/utils/usePricePrecision.formatPrice` | 严禁自造 toFixed |
| 测试 fixture 要清表怎么办 | `知识库/开发流程/测试体系.md` §fixture 卫生 | **禁止清表**，用 `t_` 前缀 + 隔离 trd_date=`99990718` |
| 加新表 / 改 schema | `scripts/gen_tables.py --table <name>` | 跑前先读 `知识库/数据库/Schema说明.md` |
| status 显示错误 | `client/src/utils/format.js` + `STATUS_LABEL` + `STATUS_RANK` | broker status 码全集白名单 |
| 改 .env / 重启服务 | `知识库/脚本工具/数据与环境工具.md` | `set -a; source server/.env; set +a;` 再启 |
| pytest 跑全套后生产数据没了 | `知识库/开发流程/测试体系.md` §安全跑测试 | **永远只跑单文件** + 先 grep 找删表 fixture |

### B. 通用模式速查（Hermes 全局 skill 还在用，按 category 排）

| 场景 | Skill |
|------|-------|
| 元规则 / 用户偏好 | `using-superpowers` + `user-workflow-preferences` + `memory-starter-kit` |
| 调试 4 阶段 root cause | `systematic-debugging` |
| 软件工程生命周期 / TDD / 评审 | `software-engineering-lifecycle` |
| 知识库审计 / gap 分析 | `knowledge-base-audit` |
| 写代码前查 git 远程 / OpenSpec | `large-code-preflight-git-fetch` |
| Hermes 配置 / 调度 / 多模型 | `hermes-agent` + `hermes-multi-model-routing` + `hermes-themes` + `hermes-desktop-plugins` |
| Claude Code sandbox 中转 | `hermes-sandbox-cc` + `hermes-sandbox-cli-agent` |
| Hermes terminal SLA / OOB | `v120-hermes-tool-sla` |
| patch GBK 编码损坏 | `patch-tool-gbk-encoding-traps` |
| Skill 编写格式 | `hermes-agent-skill-authoring` |
| 删 SPA feature（router + 导航联动） | `spa-feature-removal-checklist` |
| 服务 watchdog cron | `service-watchdog-cron-pattern` |
| git commit 拆分（一 diff 多主题） | `git-commit-splitting` |
| 简写代码 3 agent 并行 | `simplify-code` |
| Kanban 编排 / worker | `kanban-orchestrator` + `kanban-worker` |
| Webhook 触发 agent run | `webhook-subscriptions` |
| FastAPI async 调同步 IO | `fastapi-async-def-sync-call-blocking` |
| WS 跨线程 broadcast | `fastapi-cross-thread-ws-broadcast` |
| 表代码生成 | `table-codegen` + `database-migration` |
| 派生列 backfill | `derived-column-production-backfill` |
| Vue3 + Element Plus 样式 | `vue3-element-plus-scoped-css-gotchas` + `element-plus-prop-api-migration` |
| Vue3 Pinia 启动顺序 | `vue3-pinia-spa-bootstrap-gate` |
| Vue3 composable ref 注入 | `vue3-composable-ref-injection-pitfalls` |
| Vue3 CodeMirror 6 集成 | `vue3-codemirror-6-editor-integration` |
| 前端精度/单位 round | `frontend-precision-and-unit-rounding` |
| 前端 API axios 401/404 | `frontend-api-conventions` |
| 前端 auth + 路由守卫 | `frontend-auth-and-routing` |
| 前端 token keepalive | `frontend-token-keepalive` |
| 前端配置工具栏 | `frontend-config-toolbar-pattern` |
| Vite build vs dev 不一致 | `vite-build-vs-dev-divergence` |
| Jupyter live kernel | `jupyter-live-kernel` |
| Native MCP client | `native-mcp` |
| 通用 GitHub | `github-auth` + `codebase-inspection` |
| 通用 DevOps | `infrastructure-operations` + `nginx-proxy-manager-wildcard-cert` + `tls-certificate-lifecycle` |
| 通用测试 | `test-create-probe` + `dogfood` |
| 办公套件 | `notion` / `obsidian` / `apple-notes` / `apple-reminders` / `linear` / `airtable` / `google-workspace` / `imessage` |
| 文件/文档 | `docx` / `pdf` / `ocr-and-documents` / `xlsx` / `powerpoint` / `nano-pdf` |
| 信息搜索 | `arxiv` / `blogwatcher` / `llm-wiki` / `polymarket` / `research-paper-writing` |
| 桌面应用 | `computer-use` + `findmy` + `tui-widgets` |
| 邮件 | `himalaya` |
| 地图 | `maps` |
| 团队会议 | `teams-meeting-pipeline` |
| 股票代码源 | `china-stock-symbol-list-sources` |
| 桌面宠物 | `petdex` |
| 收尾 | `yuanbao` |

### C. 旧 skill 内容保留位置

旧 39 个 EvTrade skill + finance 3 个 + topology 1 个 + claude-demo 1 个 = **44 个**全部 archive 到：

```
~/.hermes/skills/.archive/
  ├── evtrade-ai-assistant-architecture/  (已废, AI 助手架构)
  ├── evtrade-ai-claudedemo/             (已废, 早期 claudedemo 模式)
  ├── evtrade-ai-rest-call-sop/          (AI 助手被废后无意义)
  ├── evtrade-atomic-upsert-tablebase-pattern/
  ├── evtrade-backend-false-error-diagnosis/
  ├── evtrade-backtest-observability/
  ├── evtrade-backtest-performance-and-risk/
  ├── evtrade-broker-protocol-field-audit/
  ├── evtrade-endpoint-testing/
  ├── evtrade-frontend-cross-day-cache-architecture/
  ├── evtrade-frontend-price-panel-antipattern/
  ├── evtrade-hermes-skill-bridge/
  ├── evtrade-hq-quota-push-protocol/
  ├── evtrade-iq-broker-period-coverage/
  ├── evtrade-live-ui-debug-workflow/
  ├── evtrade-pkg-install-safety/
  ├── evtrade-pos-push-broker-driven-position/
  ├── evtrade-push-handler-position-flow/  (已 ARCHIVED, v118+ 改 broker 权威直覆盖)
  ├── evtrade-pytest-fixture-db-safety/
  ├── evtrade-quota-udp-pipeline/
  ├── evtrade-rpc-health-3state/
  ├── evtrade-schema-governance/
  ├── evtrade-script-strategy/
  ├── evtrade-service-env-injection/
  ├── evtrade-status-inference-traps/
  ├── evtrade-t0-aggregator-day-pnl/
  ├── evtrade-tablebase-pitfalls/
  ├── evtrade-table-codegen/
  ├── evtrade-table-patterns/
  ├── evtrade-test-fixture-hygiene/
  ├── evtrade-vue3-reactive-el-table-cell-design/
  ├── evtrade-whitelist-extractor-field-loss/
  ├── evtrade-ws-channel-reuse-pattern/
  ├── evtrade-ws-push-fanout/
  ├── evtrade-ws-system-status-channel/
  ├── hermes-actual-api-vs-claimed/
  ├── invest-analyst/                      (用户拍板不做投资分析)
  ├── market-news-investor/                (同上)
  └── v120-evtrade-services-topology/
```

如需查旧内容：

```bash
ls ~/.hermes/skills/.archive/ | grep evtrade
cat ~/.hermes/skills/.archive/evtrade-broker-protocol-field-audit/SKILL.md
```

**原则**：新工作不直接读 archive skill，先按 A 表查知识库 / 脚本；只有知识库缺失时才回退到 archive。
