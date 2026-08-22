# EvTrade — AI 助手全局规则入口（Claude Code / Hermes Agent）

> 本文件是 EvTrade 项目**最高优先级**的全局规则入口。**任何 AI 助手（Claude Code / Hermes / 其他）执行任务前必读**。
> 改代码前必看 `openspec/AGENTS.md`；业务约束必看 `知识库/全局规范.md` + `知识库/项目总览.md`。

---

## 一、项目内部规则（强制遵守）

### 1. 每次执行任务前先 `git pull` 拉取最新

执行任何任务（改代码、查文档、提交 commit）的**第一步**，必须是：

```bash
git pull origin master
```

若 pull 失败（有未提交改动 / 冲突 / 网络问题）→ 立即停止报告，不擅自处理。  
若本地领先 origin 且无需同步 → 可跳过 pull，但必须 `git status` + `git log -3 origin/master..HEAD` 确认。

### 2. 项目管理准则遵从 `知识库/项目总览.md` + `知识库/全局规范.md`

- **`知识库/项目总览.md`** 是项目定位、四大服务、架构与数据流、技术栈、知识库导航的**单一事实来源**。
- **`知识库/全局规范.md`** 是知识库与代码同步的**最高工作准则**——任何需求、BUG、重构都必读：
  - 知识库定位（Single Source of Truth）
  - 修改流程（强约束，顺序不可颠倒）
  - 改动范围铁律（Scope Control）
  - 知识库文件规范（命名、长度、位置）
  - 知识库目录 ↔ 代码目录映射
  - 注释与历史记录规范（禁止版本标注）

⚠️ **违反上述两条规则 = 违反项目工作纪律**。

---

## 二、项目一句话

Vue3 + FastAPI 量化交易 Web 平台。**业务数据 MySQL 优先**（v4 改造后）：
- 委托/成交/持仓/资金：MySQL 是展示源
- 下单/撤单/对账：调 QMT 柜台 RPC
- 行情：msgpacket RPC + RabbitMQ FANOUT → 独立 hqserver WebSocket

后端 = 薄包装 + JWT/RBAC + DB 落库 + WebSocket 推送；前端 = 12 页面 + Pinia 缓存。

详细架构见 [`openspec/AGENTS.md` § 架构](openspec/AGENTS.md) 与 [`知识库/项目总览.md`](知识库/项目总览.md) § 架构与数据流。

---

## 三、核心工作流（强约束，顺序不可颠倒）

```text
1. 读知识库 → 补全/修正知识库
   ↓
2. 创建 OpenSpec change（proposal.md + tasks.md + spec-deltas/）
   ↓
3. 改代码 + 测试（按 tasks.md 走）
   ↓
4. 归档：spec 合并到 openspec/specs/<cap>/spec.md + mv change → archive/
```

**步骤 0 检查清单**（处理任何需求/BUG 前必对照打勾）：

- [ ] 已用 Glob/Grep 扫过相关 `openspec/specs/<cap>/spec.md` 与 `openspec/changes/` 现有条目
- [ ] 涉及的术语、约束、影响面在知识库中有完整描述
- [ ] 若知识库缺说明，先在 `openspec/specs/<cap>/spec.md` 补全；逻辑断裂处先修补
- [ ] 步骤 1 的 `proposal.md` 引用了知识库对应章节（可点击跳转）
- [ ] 知识库与现状一致后，才进入步骤 1

详见 [`openspec/AGENTS.md`](openspec/AGENTS.md) § 改东西的流程 与 [`知识库/全局规范.md`](知识库/全局规范.md) § 二、修改流程。

---

## 四、约定（业务铁律）

- **业务数据源（v4）**：MySQL（orders/trades/positions/assets）是展示源；RPC 只用于下单/撤单/对账时的事实写入
- **下单流程**：本地 INSERT(status=48) → 调 ord_stk(remark=order_no) → 改 status=49/55 → WS 推
- **推送流程**：4 类 push → push_handlers 写 DB → WS 推 Vue
- **查询流程**：纯 DB SELECT，不调 RPC；按 trading_day 默认 = 激活日
- **三屏障**：未做日初 / 非交易时段 / 非 trader 角色 → 503（查询不受限）
- **WS 频道命名**：`order_update` / `trade_update` / `position_update` / `asset_update` / `quote_update`
- **RPC 响应统一**：`{code, msg, list}`（code=0 成功，前端 axios 拦截器自动展平）
- **配置分层**：`server/.env`（FastAPI）+ `HQ_*`（hqserver，与 server 共享 .env）
- **T0 配平**：`calc_t0_volume(target * coefficient) → 整手取整`（买向下/卖向上）
- **order_no**：8 位数字（DB 序列表原子 UPSERT），当 order_remark 透传

详见 [`知识库/项目总览.md`](知识库/项目总览.md) § 架构与数据流 与 [`openspec/AGENTS.md`](openspec/AGENTS.md) § 约定。

---

## 五、Commit 规范（v6）

**按功能维度拆 commit**——每个 commit 应对应**一个独立功能/模块/目的**，不要把无关改动混在一起：

| 场景 | 拆 commit 方式 |
|---|---|
| 一个 change（含数据库迁移 + ORM + service + API + 前端） | 按层拆：migration / orm / service / api / frontend，每层 1 commit |
| 一个 bug fix 跨多文件 | 先 fix + 验证 1 commit，再 test 改进另 1 commit |
| 文档与代码同改 | 文档单独 1 commit（`docs(...)`），代码按功能另 1 commit |
| lint 清理 | 整个批次 1 commit（`chore(lint): ruff --fix 66 个 F401`）—— 一个**单一目的**仍是单一 commit |
| 多模型试水 | 验证脚本 1 commit + 配置改动 1 commit + 文档 1 commit |

**反模式**（避免）：
- ❌ "今天所有改动 1 个 mega commit"（无法 revert 单个功能）
- ❌ "1 commit 改 N 个不相关模块"（diff 难 review）
- ❌ "1 commit 修 bug + 加新功能 + 改 docs"（3 件事纠缠）

**例外**：lint auto-fix / 格式整理可以批量 1 commit，因为它们是**单一目的**（清理），不是多目的混合。

**commit 前必做**：
1. `git diff --stat` 看改动范围是否单一功能
2. `git log -1` 校验上一个 commit hash（防 AI 误报，git-safety skill）
3. commit message 用单行 `-m`（heredoc 在 AI 工具中会 timeout，经验教训）
4. **不自动 push**——除非用户明确拍板

---

## 六、Python 代码风格（强制）

- **缩进**：4 空格（禁止 tab）
- **行宽**：单行不超过 120 字符
- **命名**：
  - 变量/函数：`snake_case`（如 `get_user_info`）
  - 类名：`PascalCase`（如 `TradingClock`）
  - 常量：`UPPER_SNAKE_CASE`（如 `MAX_LIMIT`）
  - 文件名：全小写加划线（如 `script_strategy.py`）
- **注释**：复杂逻辑必须注释，说明**为什么**而非**是什么**
- **类型**：函数参数和返回值必须标注类型（`def foo(x: int) -> str:`）
- **docstring**：函数需短描述 + 参数 + 返回 + 示例（参考 Google/NumPy 风格）

---

## 七、Git 规范（强制）

- **提交信息格式**：`<type>(scope): <subject>`（type: feat / fix / docs / style / refactor / test / chore）
- **每个 commit 只做一件事**
- **提交前必做** `git diff` 检查改动范围
- **commit message 单行 `-m`**（heredoc 在 AI 工具中会 timeout，2026-08 经验）
- **不自动 push**（除非用户明确拍板）

---

## 八、测试规范（强制）

- **所有新增函数必须写单元测试**
- **测试文件命名**：`<模块>_test.py` 或 `test_<模块>.py`（与现有 `server/tests/` 风格一致）
- **测试函数命名**：`test_<函数名>_<场景>`
- **目标通过率**：100%（新写的测试必须全过）
- **核心目标**：
  - `pytest hq/` 18/18
  - `pytest server/test_*.py` 75/75
  - 任何破坏性 refactor 必须保证上述数字不降低

---

## 九、重构规范（强制）

- **重构前先确认已有测试覆盖**
- **每次重构只做一件事**（按 v6 commit 规范拆 commit）
- **重构后立即运行测试**（pytest + npm run build 如涉及前端）
- **批量删 import / 大文件改动时**，每步 patch 后跑 `python -c "import server.X"` 验 import 不破

---

## 十、错误处理（强制）

- **不允许**裸露的 `except: pass`
- **异常必须记录日志**（`log.exception(...)`）或**重新抛出**（`raise`）
- **网络请求必须设 timeout**（默认 30s）
- **async 路由调同步 IO** 必须 `await asyncio.to_thread(fn)` 包装（2026-08-20 实战教训：单进程 uvicorn event loop 会阻塞整进程）

---

## 十一、知识库同步铁律（不可绕过）

每次改代码，**必须同步更新对应的知识库文档**：

| 改动类型 | 必同步 |
|---|---|
| 后端 API 改动 | `知识库/后端服务/` 对应模块的 spec.md |
| 前端视图改动 | `知识库/前端/` 对应 spec.md |
| 数据库 schema 改动 | `知识库/数据库/` + 跑 `scripts/sync_schema.py` |
| 行情/策略服务改动 | `知识库/行情服务/` 或 `知识库/策略服务/` |
| 跨服务改动 | 更新 `openspec/specs/<cap>/spec.md` + 创建 change |

详见 [`知识库/全局规范.md`](知识库/全局规范.md) § 三、改动范围铁律。

---

## 十二、长任务处理（强制）

遇到复杂任务（≥3 步）时：

```
1. 拆分为独立子任务
2. 用 delegate_task 并行跑（M2.7 subagent）
3. 主 agent 拿到报告后**二次验证**（grep / read_file / ls）
4. 不要直接采信 subagent 报告，必须二次验证
5. 全部完成后跑 pytest + commit + 归档
```

⚠️ **2026-08-22 教训**：M2.7 subagent 会凭"任务描述"瞎编不存在的 API（如 `Positions.delete_all()` 实际不存在）。**主 agent 必须二次验证** `TableBase` 真实方法列表，不能盲改。

---

## 十三、代码审查清单（commit 前自查）

- [ ] 变量/函数命名清晰
- [ ] 复杂逻辑有注释（说明**为什么**）
- [ ] 函数有类型标注 + docstring
- [ ] 异常处理符合 § 十
- [ ] 新增/修改函数有测试覆盖
- [ ] 没有 TODO/FIXME 未处理
- [ ] `git diff --stat` 显示改动范围单一功能
- [ ] 知识库已同步（§ 十一）
- [ ] pytest 全过（或记录失败原因）

---

## 文档体系索引

| 文档 | 职责 | 何时读 |
|---|---|---|
| `CLAUDE.md`（本文件） | AI 助手全局规则入口 + 项目一句话 + 工作流索引 | **每次任务前** |
| `openspec/AGENTS.md` | OpenSpec 详细工作流 + Commit 规范 v6 | 改代码前 |
| `知识库/项目总览.md` | 项目定位、四大服务、架构、数据流 | 了解项目背景 |
| `知识库/全局规范.md` | 知识库与代码同步铁律（最高准则） | 改代码前 |
| `知识库/目录索引.md` | 知识库全目录导航 | 找具体模块文档 |
| `openspec/specs/<cap>/spec.md` | 各 capability 能力级需求 | 改具体模块前 |

---

## 当前活跃 change

`openspec/AGENTS.md` § 当前活跃 change 段维护实时列表。

最近归档的 change（参考）：
- `archive/2026-06-14-persistence-and-t0`（v4 实施）
- `archive/2026-08-08-structure-cleanup-no-logic-change`（partial, 后续转 `2026-08-22-structure-cleanup-remaining`）
- `archive/2026-08-21-scriptdev-fix-compile`
- `archive/2026-08-23-delete-orm-layer`（A.8：删 ORM 层，数据访问统一 tables/）
- `archive/2026-08-23-script-visibility-toggle`（ScriptDev 脚本公开/私有开关）
- `archive/2026-08-23-rpc-test-mode`（RPC 测试模式：固定应答，不发真实请求）
