# 2026-08-13-short-name-etf-run — short_name 里 ETF 只剩 E，ASCII 串要整串保留

## Why

用户反馈：添加/修改证券信息时，名称里的 ETF 字母在简称（short_name）里只剩 E。
实测（pypinyin）：

```
'创业板ETF'   → CYBE     (应为 CYBETF)
'华夏上证50ETF' → HXSZ5   (应为 HXSZ50ETF)
'沪深300ETF'  → HS3      (应为 HS300ETF)
'银行ETF'     → YHE      (应为 YHETF)
```

## 根因

`server/services/short_name.py::to_short_name` 对 `pypinyin.lazy_pinyin(name)` 每个段
取 `s[0]`。pypinyin 把连续 ASCII 串（`ETF` / `50ETF`）当**一个段**返回，`s[0]` 只留
首字符 → ETF 只剩 E、50ETF 只剩 5。ST 前缀剥离逻辑不受影响。

## What Changes

### server/services/short_name.py

`to_short_name` 主体改用 `re.split(r"([A-Za-z0-9]+)", name)` 把 ASCII 字母/数字串从
中文里分离：

- **汉字段** → pypinyin 取首字母（行为不变）
- **ASCII run 段**（`ETF` / `50ETF` / `A` / `300`…）→ 整串保留并大写

```
'创业板ETF'    → 创业板(CYB) + ETF → CYBETF
'华夏上证50ETF' → 华夏上证(HXSZ) + 50ETF → HXSZ50ETF
'沪深300ETF'   → 沪深(HS) + 300ETF → HS300ETF
'京东方A'      → 京东方(JD) + A → JDA   (与原行为一致, 无回归)
```

### openspec/specs/stocks/spec.md REQ-STOCK-007

算法第 3 步补充：ASCII 字母/数字连续串整串保留（大写），仅汉字取拼音首字母。

## 不做的事

- ❌ 不改 ST 前缀剥离逻辑（行为不变）
- ❌ 不重刷历史数据（dev stocks 表当前为空；若生产有存量可跑 backfill_short_name.py 复用本函数）

## 关联

- 上游：`REQ-STOCK-007`（short_name 自动生成）；`server/services/short_name.py`
- 影响面：create_by_admin / update_by_admin / backfill_short_name 全部路径（单一可信来源）
