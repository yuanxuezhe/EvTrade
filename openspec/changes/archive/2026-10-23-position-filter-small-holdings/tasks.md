# Tasks: position-filter-small-holdings

## C1 — OpenSpec change 工件 (1 commit)

- [x] proposal.md
- [x] spec-deltas/frontend.md (REQ-FE-557 段)
- [x] spec-deltas/configuration.md (REQ-SE-014 段)
- [x] tasks.md (本文件)

## C2 — spec merge (1 commit)

- [x] `openspec/specs/frontend/spec.md` 追加 `## REQ-FE-557` 段
- [x] `openspec/specs/configuration/spec.md` 追加 `## REQ-SE-014` 段

## C3 — 后端 sysconfig seed (1 commit)

- [x] `server/services/sysconfig/__init__.py` `DEFAULT_CONFIGS` 加:
      `{"cfg_key": "position_filter_min_vol", "cfg_val": "0", "desc": "持仓查询页过滤小持仓阈值 (股数); 勾选「过滤小持仓」时 vol<=此值的行隐藏, 0=不过滤"}`
- [x] 验证: 服务重启后 `sys_config` 表出现该行 (默认 user='0')
- [x] 验证: `GET /api/sysconfig/position_filter_min_vol` 返 200 + cfg_val='0'

## C4 — 前端 HoldingsPanel checkbox (1 commit)

- [x] `client/src/components/trade/HoldingsPanel.vue`:
  - [x] import `sysconfigApi` from `../../api/sysconfig`
  - [x] 新增 `filterSmall = ref(true)` (默认勾上)
  - [x] 新增 `minVolThreshold = ref(0)`
  - [x] onMounted 读 `sysconfigApi.get('position_filter_min_vol')` → 写入 `minVolThreshold`
  - [x] `filteredPositions` computed 增加小持仓过滤分支:
        `filterSmall && vol <= minVolThreshold` → 剔除
  - [x] 工具栏 `tp-header` 加 `el-checkbox` 「过滤小持仓」+ 阈值提示
  - [x] 读取失败 (403/404/网络) 时降级: 阈值 = 0 + console.warn, 不阻塞面板
- [x] 勾选状态不持久化 (每次进页面默认勾上 — 用户要求「取消勾选则全部显示」)

## C5 — 知识库同步 (1 commit)

- [x] `知识库/前端/` 对应 spec 补「持仓查询页过滤小持仓」
- [x] `知识库/后端服务/` sysconfig 相关 spec 补新 cfg_key

## C6 — 验证 (无 commit)

- [x] `cd client && npm run build` 通过
- [x] `pytest server/tests/<相关单文件>.py -v` 通过
- [x] 手工验证 (curl + 逻辑推演): 阈值 0 / 阈值 100 两种情况下的过滤结果

## C7 — 归档 + 提交 + 推送 + 重启 (1 commit)

- [x] `git mv openspec/changes/2026-10-23-position-filter-small-holdings openspec/changes/archive/`
- [x] `openspec/AGENTS.md` 追 ✅ 已归档 行
- [x] 提交 + `git push origin master`
- [x] `evctl restart` (frontend + backend)
- [x] `evctl status` 确认 4 服务 healthy
