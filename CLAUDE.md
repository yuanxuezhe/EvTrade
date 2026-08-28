# EvTrade — AI 助手全局规则入口（Claude Code / Hermes Agent）

> 本文件是 EvTrade 项目**最高优先级**的全局规则入口。**任何 AI 助手（Claude Code / Hermes / 其他）执行任务前必读**。
> 改代码前必看 `openspec/AGENTS.md`；业务约束必看 `知识库/全局规范.md` + `知识库/项目总览.md`。

---

## 一、项目规则（执行任务前必做）

### 1. 先 `git pull` 拉最新

```bash
git pull origin master
```

pull 失败（有未提交改动 / 冲突 / 网络问题）→ 立即停止报告，不擅自处理。
本地领先 origin 且无需同步 → 可跳过 pull，但必须 `git status` + `git log -3 origin/master..HEAD` 确认。

### 2. 项目管理遵循知识库

- **`知识库/项目总览.md`** = 项目定位、四大服务、架构、数据流的单一事实来源
- **`知识库/全局规范.md`** = 知识库与代码同步的最高工作准则
- 违反上述两条 = 违反项目工作纪律

---

## 二、项目一句话

Vue3 + FastAPI 量化交易 Web 平台。**业务数据 MySQL 优先**（v4 改造后）：
- 委托/成交/持仓/资金：MySQL 是展示源
- 下单/撤单/对账：调 QMT 柜台 RPC
- 行情：msgpacket RPC + RabbitMQ FANOUT → 独立 hqserver WebSocket

后端 = 薄包装 + JWT/RBAC + DB 落库 + WebSocket 推送；前端 = 12 页面 + Pinia 缓存。
详细架构见 `知识库/项目总览.md` § 架构与数据流。

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

**步骤 0 检查清单**：
- [ ] 已 Glob/Grep 扫过 `openspec/specs/<cap>/spec.md` 与 `openspec/changes/` 现有条目
- [ ] 涉及术语、约束、影响面在知识库中有完整描述
- [ ] 若知识库缺说明，先在 `openspec/specs/<cap>/spec.md` 补全
- [ ] proposal.md 引用了知识库对应章节（可点击跳转）

详见 `openspec/AGENTS.md` § 改东西的流程 与 `知识库/全局规范.md` § 二、修改流程。

---

## 四、业务铁律（约定）

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

---

## 五、Commit 规范（v6）

**按功能维度拆 commit**——每个 commit 一个独立功能/模块/目的：

| 场景 | 拆 commit 方式 |
|---|---|
| 一个 change（含数据库迁移 + ORM + service + API + 前端） | 按层拆：migration / orm / service / api / frontend，每层 1 commit |
| bug fix 跨多文件 | 先 fix + 验证 1 commit，再 test 改进另 1 commit |
| 文档与代码同改 | 文档单独 1 commit（`docs(...)`），代码按功能另 1 commit |
| lint 清理 | 整个批次 1 commit（单一目的=清理） |

**反模式**：mega commit / 1 commit 改 N 个不相关模块 / 1 commit 修 bug + 加新功能 + 改 docs（3 件事纠缠）

**commit 前必做**：
1. `git diff --stat` 看改动范围是否单一功能
2. commit message 用单行 `-m`（heredoc 在 AI 工具中会 timeout）
3. **不自动 push**——除非用户明确拍板

---

## 六、测试规范

- **所有新增函数必须写单元测试**
- **测试文件命名**：`<模块>_test.py` 或 `test_<模块>.py`
- **测试函数命名**：`test_<函数名>_<场景>`
- **目标通过率**：100%（新写的测试必须全过）

- **核心目标（2026-08-27 末基线）**：
-  - `pytest server/tests/` → **58 collected / 58 passed / 0 failed** ✅ 全部通过
  - 旧基线 71/64/7 (08-23) → 133/121/12 (08-27 P0-1 后) → 130/125/5 (08-27 P1-1② 后) → 74/73/1 (08-27 P1-1③ 后) → **58/58/0 (08-27 收尾)**
- 旧基线已废弃——`test_place_async.py` (P1-1② done) + `test_quota_batch.py` (P1-1① done) + `test_orders_cancel.py` (P1-1③ done)
- 删 `test_v78_skip_rebroadcast.py` (v78 旧 + fixture 删表) + `test_pos_push_diff.py` (v118 前 diff 语义已废)

**绝不允许 fixture 删生产数据**：
- `DELETE FROM orders/trades/sys_status/users(admin/trader/t_ 除外)` / `ALTER TABLE AUTO_INCREMENT` / SQLite / CREATE 测试临时表 / RESET sys_status 全禁
- 跑测试前先 grep：`grep -rE "DELETE FROM orders|TRUNCATE" server/tests/` 必须 0 命中
- 永远只跑单文件：`pytest server/tests/test_X.py -v`，不跑全套

详见 `知识库/开发流程/测试体系.md`。

---

## 七、错误处理

- **不允许**裸露的 `except: pass`
- **异常必须记录日志**（`log.exception(...)`）或**重新抛出**（`raise`）
- **网络请求必须设 timeout**（默认 30s）
- **async 路由调同步 IO** 必须 `await asyncio.to_thread(fn)` 包装（2026-08-20 实战教训：单进程 uvicorn event loop 会阻塞整进程）

---

## 八、知识库同步铁律（不可绕过）

每次改代码，**必须同步更新对应的知识库文档**：

| 改动类型 | 必同步 |
|---|---|
| 后端 API 改动 | `知识库/后端服务/` 对应模块的 spec.md |
| 前端视图改动 | `知识库/前端/` 对应 spec.md |
| 数据库 schema 改动 | `知识库/数据库/` + 跑 `scripts/sync_schema.py` |
| 行情/策略服务改动 | `知识库/行情服务/` 或 `知识库/策略服务/` |
| 跨服务改动 | 更新 `openspec/specs/<cap>/spec.md` + 创建 change |

详见 `知识库/全局规范.md` § 三、改动范围铁律。

---

## 九、commit 前自查（精简版）

- [ ] `git diff --stat` 显示改动范围单一功能
- [ ] 知识库已同步（§ 八）
- [ ] pytest 全过（或记录失败原因）
- [ ] 没有 TODO/FIXME 未处理
- [ ] 没有改动范围超出当前 change

---

## 文档体系索引

| 文档 | 职责 | 何时读 |
|---|---|---|
| `CLAUDE.md`（本文件） | AI 助手全局规则入口 + 项目一句话 + 工作流索引 | **每次任务前** |
| `openspec/AGENTS.md` | OpenSpec 详细工作流 + Commit 规范 v6 | 改代码前 |
| `知识库/项目总览.md` | 项目定位、四大服务、架构、数据流 | 了解项目背景 |
| `知识库/全局规范.md` | 知识库与代码同步铁律（最高准则） | 改代码前 |
| `知识库/目录索引.md` | 知识库全目录导航 | 找具体模块文档 |
| `知识库/开发流程/Agent工作指南.md` | AI 助手工作流 + skill 速查表 | 实施任务前 |
| `openspec/specs/<cap>/spec.md` | 各 capability 能力级需求 | 改具体模块前 |

---

## 当前活跃 change

`openspec/AGENTS.md` § 当前活跃 change 段维护实时列表（单一事实来源，本文件不重复）。

> 历史归档清单以 `openspec/changes/archive/` 实际目录为准；如需索引请看 `openspec/AGENTS.md`。