# Tasks: position-filter-small-holdings

## C1 — OpenSpec change 工件 (1 commit)

- [x] proposal.md
- [x] spec-deltas/frontend.md (REQ-FE-557 段)
- [x] spec-deltas/configuration.md (REQ-SE-014 段)
- [x] tasks.md (本文件)

## C2 — spec merge (1 commit)

- [x] `openspec/specs/frontend/spec.md` 追加 `## REQ-FE-557` 段 (commit `340e9e4`)
- [x] `openspec/specs/configuration/spec.md` 追加 `## REQ-SE-014` 段 (commit `340e9e4`)

## C3 — 后端 sysconfig seed (1 commit)

- [x] `server/services/sysconfig/__init__.py` `DEFAULT_CONFIGS` 加:
      `{"cfg_key": "position_filter_min_vol", "cfg_val": "0", "desc": "交易下单页持仓面板过滤小持仓阈值 (股数); 勾选「过滤小持仓」时 vol<=此值的行隐藏, 0=不过滤"}` (commit `532fc27`)
- [x] 验证: 服务重启后 `sys_config` 表出现该行 (默认 user='0') — 实测 1 行, user='0'
- [x] 验证: `GET /api/sysconfig/position_filter_min_vol` 返 200 + cfg_val — 实测 200, cfg_val='100' (管理员已改)

## C4 — 前端 HoldingsPanel checkbox (1 commit)

- [x] `client/src/components/trade/HoldingsPanel.vue` (commit `4cacab5`):
  - [x] import `sysconfigApi` from `../../api/sysconfig`
  - [x] 新增 `filterSmall = ref(true)` (默认勾上 — 用户 2026-10-23 明确)
  - [x] 新增 `minVolThreshold = ref(0)`
  - [x] onMounted 读 `sysconfigApi.get('position_filter_min_vol')` → 写入 `minVolThreshold`
  - [x] `filteredPositions` computed 增加小持仓过滤分支:
        `filterSmall && vol <= minVolThreshold` → 剔除
  - [x] 工具栏 `tp-header` 加 `el-checkbox` 「过滤小持仓」+ 阈值提示 `(显示大于N股持仓)`
  - [x] 读取失败 (403/404/网络) 时降级: 阈值 = 0 + console.warn, 不阻塞面板
- [x] 勾选状态不持久化 (每次进页面默认勾上 — 用户要求「取消勾选则全部显示」)

## C5 — 知识库同步 (1 commit)

- [x] `知识库/前端/组件/交易组件.md` 加 HoldingsPanel 过滤小持仓 段 (commit `b1988a2`)
- [x] `知识库/后端服务/系统管理/系统配置.md` DEFAULT_CONFIGS 表补 `position_filter_min_vol` (commit `b1988a2`)

## C6 — 验证 (无 commit)

- [x] `cd client && npm run build` 通过 (24.76s, 主图 1326.50 kB / gzip 430.94 kB)
- [x] `uv run python -m pytest server/tests/ -q` → **126 passed** (全绿)
- [x] `npx vitest run ../tests/client/components/trade/HoldingsPanel.test.js` → **11 passed** (commit `7f1df91`)
- [x] 逻辑推演 6 case 全 PASS (阈值 0 / 阈值 100 / 取消勾选 / keyword AND 叠加)
- [x] 实测: `GET /api/sysconfig/position_filter_min_vol` → 200 + cfg_val='100'; sys_config 表 user='0' 1 行

## C7 — 归档 + 提交 + 推送 + 重启 (1 commit)

- [x] `git mv openspec/changes/2026-10-23-position-filter-small-holdings openspec/changes/archive/` (commit `340e9e4`)
- [x] `openspec/AGENTS.md` 追 ✅ 已归档 行 (commit `340e9e4`)
- [x] 提交 (本 change 共 6 commit: `50f9ecd` / `340e9e4` / `532fc27` / `4cacab5` / `b1988a2` / `7f1df91`)
- [x] `git push origin master`
- [x] `evctl restart` (frontend + backend)
- [x] `evctl status` 确认 4 服务 healthy
