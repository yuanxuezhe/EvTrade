# Tasks: stock-info-crawler

## Commit 1: 数据层(orm + migration + repo + spec)

- [ ] `server/models/orm.py`:+ `Stock` ORM class(15 字段 + 2 索引)
- [ ] `server/migrations/2026-07-10-create-stocks-table.py`:DDL + load_dotenv + 幂等
- [ ] 运行 migration 验证表创建成功
- [ ] `server/repo/stocks.py`:+ upsert + get_by_code + list_by_industry + list_all
- [ ] `openspec/specs/data-model/spec.md`:+ §12 stocks 表
- [ ] `openspec/specs/stocks/spec.md`:+ REQ-STOCK-001/002/003 spec
- [ ] commit:`feat(orm): stocks 表 + 增量 upsert repo`

## Commit 2: 业务层(crawler + sync + API + WS)

- [ ] `server/crawler/__init__.py`
- [ ] `server/crawler/sources/eastmoney.py`:2 个 API 适配
  - `fetch_base_info(stock_code) -> dict`(基本信息:名称/行业/市场/股本/PE/PB/市值)
  - `fetch_intro(stock_code) -> str`(公司简介)
- [ ] `server/crawler/runner.py`:异步循环 + 进度回调 + 优雅停止信号
- [ ] `server/services/sync/__init__.py`
- [ ] `server/services/sync/task.py`:SyncTask dataclass(state/counters/timing)
- [ ] `server/services/sync/manager.py`:start/stop/status + WS broadcast
- [ ] `server/api/sync.py`:3 个 REST 端点
- [ ] `server/api/stocks.py`:2 个 REST 端点
- [ ] `server/ws/endpoint.py`:+ sync_update 频道处理
- [ ] `server/main.py`:+ 2 个 router 注册 + sync_update 频道白名单
- [ ] `tests/test_crawler_eastmoney.py`:mock 响应 + 解析测试
- [ ] `tests/test_sync_manager.py`:start/stop/status 单元测试
- [ ] commit:`feat(crawler): 东方财富适配 + 后台同步任务 + WS 进度推送`

## Commit 3: 前端层(Sync.vue + stores + router)

- [ ] `client/src/api/sync.js`:POST/DELETE/GET wrappers
- [ ] `client/src/stores/sync.js`:Pinia store + WS 订阅 + 进度状态
- [ ] `client/src/stores/stocks.js`:Pinia store + 缓存 + WS 推送更新
- [ ] `client/src/views/Sync.vue`:进度管理页面
- [ ] `client/src/router/index.js`:+ `/admin/sync` 路由(admin 守卫)
- [ ] 菜单项 admin 角色可见(quota/quota 不显示)
- [ ] `client/src/api/sync.js` + `stocks.js`:axios withCredentials + JWT
- [ ] `npx vite build` 0 错误
- [ ] commit:`feat(fe): 同步管理页面 + WS 实时进度 + stocks 缓存`

## Verification

- [ ] MySQL `stocks` 表创建成功(15 字段)
- [ ] `pytest tests/test_crawler_eastmoney.py tests/test_sync_manager.py` 全过
- [ ] backend 启动 healthy,无 dotenv/SQLAlchemy 报错
- [ ] admin JWT → POST /api/sync/stocks → 200 OK
- [ ] 前端 `/admin/sync` 页面可见进度条 + 数字实时变化
- [ ] WS `/ws/sync_update` 推送 `stock_sync_progress` + `stock_synced` 消息
- [ ] stocks 表数据写入成功
- [ ] `npx vite build` 0 错误
- [ ] quota/quota 用户看不到 `/admin/sync` 菜单
- [ ] push 3 commit 后 origin 同步