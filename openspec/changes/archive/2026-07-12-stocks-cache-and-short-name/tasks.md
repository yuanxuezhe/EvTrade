# Tasks: 2026-07-12-stocks-cache-and-short-name

## 1. OpenSpec 4 件套（Commit 1）
- [x] proposal.md
- [x] tasks.md
- [x] spec-deltas/data-model.md（§13 stocks 表加 short_name 字段）
- [x] spec-deltas/stocks.md（新增 REQ-STOCK-006 真分页 + REQ-STOCK-007 前端缓存 + REQ-STOCK-008 autocomplete）

## 2. Migration + 依赖（Commit 2）
- [x] 写 `server/migrations/2026-07-12-add-short-name-to-stocks.py`
  - INFORMATION_SCHEMA 探测 stocks.short_name 是否存在
  - ADD COLUMN short_name VARCHAR(16) NULL
  - 幂等
- [x] `pip install pypinyin` 写入 server/requirements.txt
- [x] 跑 migration 验证: `DESC stocks` 有 short_name 列

## 3. ORM + Repo 同步（Commit 3）
- [x] `server/models/orm.py`: Stock 类加 `short_name = Column(String(16), nullable=True)`
- [x] `server/repo/stocks.py`:
  - `_ADMIN_EDITABLE_FIELDS` 加 `short_name`
  - `to_dict` 加 `short_name` 字段
  - `to_dict_from_data` 加 `short_name`
- [x] import 验证

## 4. API + 灌入脚本（Commit 4）
- [x] `server/api/stocks.py`:
  - GET /api/stocks 加 `page: int = 1` / `page_size: int = 100` 参数
  - 保留 `limit` 兼容老客户端
  - 返回 `{code, msg, list, total}`，total = COUNT(*)
  - StockUpdateRequest 加 `short_name: Optional[str] = Field(None, max_length=16)`
- [x] `server/scripts/backfill_short_name.py`:
  - 读所有 stocks 行
  - 用 pypinyin lazy_pinyin 转首字母
  - UPDATE short_name WHERE stock_code = ?
  - 进度日志 + dry_run 参数
- [x] 跑灌入: dry_run 一次 → 实跑一次
- [x] curl 验证: `?page=1&page_size=20` 返回 total=5529

## 5. 前端全量缓存 + autocomplete（Commit 5）
- [x] `client/src/stores/stocks.js` 重构:
  - cache: ref([]) 全量
  - pageRows: ref([]) 当前页
  - total: ref(0)
  - loadCache(): 循环 page=1..N page_size=100 拉全量
  - fetchPage(page, pageSize): 单页
  - searchCache(query): autocomplete 筛 cache 三路 OR
  - updateStock(code, payload): PATCH + 同步 cache + pageRows
- [x] `client/src/api/stocks.js`: list 加 page/page_size/keyword/sector/is_t0_able 参数
- [x] `client/src/components/StockCodeAutocomplete.vue`: 新组件
  - props: modelValue / placeholder / disabled
  - emit: update:modelValue / select
  - 三路 OR 筛选: code prefix OR name contains OR short_name prefix
  - el-autocomplete 包装
- [x] `client/src/views/AdminStockConfig.vue`:
  - 表格分页走后端 (pageRows/total/fetchPage)
  - 编辑弹窗的 stock_code 用 StockCodeAutocomplete
- [x] dev server 启动 + 浏览器手测:
  - 列表 5529 全量
  - 翻页 1→2→3 正常
  - 输入「600519」→ 候选 1 条
  - 输入「PAYH」→ 候选「平安银行」
  - 输入「000001」→ 候选「平安银行」+「其它 000001.*」
  - PATCH 后 cache + 表格同步

## 6. OpenSpec 主体同步（Commit 6）
- [x] `openspec/specs/data-model/spec.md` §13: Stock 表加 short_name 字段定义
- [x] `openspec/specs/stocks/spec.md`: REQ-STOCK-006 真分页 / REQ-STOCK-007 前端缓存 / REQ-STOCK-008 autocomplete
- [x] 归档 change: `mv openspec/changes/2026-07-12-stocks-cache-and-short-name/ openspec/changes/archive/`

## 7. Validation
- [x] server 启动校验 (python3 -c "import server.main")
- [x] DB schema 校验: stocks 9 字段（id 隐含）+ short_name
- [x] curl 验证: GET /api/stocks?page=1&page_size=20 → 200 + total=5529
- [x] 前端编译校验: cd client && npm run build
- [x] 等用户拍板: 是否 push 到 remote