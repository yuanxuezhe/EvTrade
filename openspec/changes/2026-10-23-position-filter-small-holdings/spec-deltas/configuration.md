# REQ-SE-007: 持仓查询小持仓过滤阈值配置 (position-filter-small-holdings 2026-10-23)

## 改动 1: `server/services/sysconfig/__init__.py` `DEFAULT_CONFIGS` 新增 seed

```python
# 持仓查询页过滤小持仓阈值 (股数) — 勾选「过滤小持仓」时 vol<=此值的行隐藏, 0=不过滤
# change 2026-10-23 (position-filter-small-holdings)
{"cfg_key": "position_filter_min_vol", "cfg_val": "0", "desc": "持仓查询页过滤小持仓阈值 (股数); 勾选「过滤小持仓」时 vol<=此值的行隐藏, 0=不过滤"},
```

## 配置项契约

| 项 | 值 |
|---|---|
| `cfg_key` | `position_filter_min_vol` |
| `cfg_val` 默认 | `"0"` |
| `desc` | `持仓查询页过滤小持仓阈值 (股数); 勾选「过滤小持仓」时 vol<=此值的行隐藏, 0=不过滤` |
| 类型 | int (`_coerce` 按 default 类型自动转; `get()` 传 `default=0` 即按 int coerce) |
| 默认 scope | `user='0'` (全局默认) |
| 消费方 | `client/src/views/CachePositions.vue` (前端读, 过滤在 IDB 数据上执行) |

## 行为约束

- 走现有 `sys_config` 表 (`_ensure_defaults()` 启动时 upsert) — **不新建表 / 不改 schema**
- 管理员在「系统配置」页 (`/system-config`) 可改 `cfg_val`
- 值非法 (非数字) → 前端 `Number.isFinite` 判定失败 → 保持默认 0, 不崩
- 阈值 0 = 语义上"不过滤" (只有 0 持仓行会被隐藏)

## 不做什么

- ❌ 不改 sysconfig API 契约 (CRUD 已有)
- ❌ 不改 `_coerce` 逻辑
- ❌ 不做 per-user 覆盖默认值以外的语义 (沿用现有 user > '0' 回退链)
