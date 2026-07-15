# Spec Delta: stocks — REQ-STOCK-007 short_name 自动生成 (含 ST 前缀保留)

> **目标文件**: `openspec/specs/stocks/spec.md`
> **追加章节**: 在 REQ-STOCK-006 之后追加 REQ-STOCK-007
> **不修改**: 现有 REQ-STOCK-001 ~ 006

---

## 新增 REQ-STOCK-007

### REQ-STOCK-007: short_name 自动生成 + ST 前缀保留 (v46+ short-name-auto)

**Module**: `server/services/short_name.py`
**调用方**: `server/repo/stocks.py` (create_by_admin / update_by_admin)
**位置**: `/admin/stock-config` 页面

**背景**:
v25 引入了 short_name 字段 (拼音首字母简称), v46 让 admin 可以手动添加股票。但当前实现存在两个问题:
1. ST 股处理错误: `ST华微` 被转成 `SHW` (把 S、T 当成拼音首字母,丢失 ST 前缀语义)
2. admin 添加时需手填 short_name, 体验差

**算法**:

```python
def to_short_name(stock_name: str) -> str:
    """拼音首字母转大写 (含 ST 前缀保留)

    步骤:
      1. 检测 ST 前缀 (大小写不敏感): *ST / ST
      2. 剥离前缀, 对剩余部分用 pypinyin.lazy_pinyin 转拼音首字母
      3. 拼接: prefix + initials (大写)
      4. 截断 16 字符
    """
```

**API 变更**:

| 端点 | 变更 |
|---|---|
| `POST /api/stocks` | 接受 stock_name, **自动**生成 short_name 入库, 不再接受 short_name 字段 |
| `PATCH /api/stocks/{code}` | 检测 stock_name 字段变化; 变化则自动重算 short_name, 不接受 short_name 字段 |

**白名单**: Pydantic 模型 (StockCreateRequest, StockUpdateRequest) **移除** short_name 字段

**Scenario**:

- **GIVEN** admin 调用 `POST /api/stocks` 时 `stock_name="*ST测试股"`
- **WHEN** 后端写入数据库
- **THEN** 自动生成 `short_name="*STCSG"` (CSG = 测试股 首字母)
- **AND** 不接受请求体中的 `short_name` 字段 (extra=forbid)

- **GIVEN** admin 调用 `PATCH /api/stocks/{code}` 修改 `stock_name="*ST实达"`
- **WHEN** 后端检测 stock_name 字段变化
- **THEN** 自动重算 `short_name="*STSD"`
- **AND** 旧 `short_name` 被覆盖

- **GIVEN** admin 调用 `PATCH /api/stocks/{code}` 只修改 `sector` 字段
- **WHEN** stock_name 未变化
- **THEN** short_name 保持不变
- **AND** 不重算

- **GIVEN** 任意 stock_name 含大小写 ST 前缀 (`*ST`, `*st`, `*St`, `*sT`, `ST`, `st`, `St`, `sT`)
- **WHEN** 调用 `to_short_name()`
- **THEN** 前缀保留到 short_name 开头 (大小写归一化为大写 ST)
