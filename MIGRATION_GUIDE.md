# EvTrade v81 ORM → tables 迁移指北

## 总原则 (用户伪代码)
所有 api/* 端点都只能调 server/tables/* 接口. 严禁直接 ORM (db.query/.filter/.add).

## 伪代码 (User Style)
```python
# 1. 单字段主键查
obj = <TableCls>.query_one(pk=val)        # 等价 db.query(M).get(pk)
# 2. 多字段主键查 (复合 PK)
obj = Orders.query_one(trd_date='x', order_no='y')
# 3. 非主键查 (单字段)
objs = <TableCls>.query_by('field', value)  # 全表扫描过滤 (前端用) / 也可带 limit=
# 4. 非主键查 (多字段 AND)
objs = <TableCls>.query_by_fields({...})
# 5. 精确查多行 (主键 IN)
objs = <TableCls>.query_all()            # 全表
# 6. 查存在性
count = aggregate(table, 'COUNT', '*', where='field=%s', params=(val,))
# 7. 对象 = Query(key); obj.xx = val; obj.update(cls, pk=...)  # 用户伪代码
obj.update(<TableCls>, pk=obj.pk)        # 等价 db.commit()
# 8. 嵌入事务: with transaction() as tx: ...
```

## 5 类替换模式
| ORM | tables 替代 |
|-----|-----------|
| db.query(M).filter_by(pk=v).first() | M.query_one(pk=v) |
| db.query(M).filter(M.field == v).all() | M.query_by('field', v) |
| db.query(M).filter(M.f1==v1, M.f2==v2).all() | M.query_by_fields({f1:v1, f2:v2}) |
| m.x = val; db.commit() | obj.x = val; obj.update(M, pk=obj.pk) |
| db.add(m); db.commit() | M.add_one(m_data) |
| db.delete(m); db.commit() | M.delete_one(pk=v) |
| Depends(get_db) | 删 (tables 全局 engine) |
| db.refresh(obj) | 删 (Row 已是 dict) |
| obj.relations | 改 query_by + 手动 join (前端做) |

## 复杂场景
- 聚合 / 子查询 / 跨表 JOIN → 用 aggregate() / scalar_query() / 自写 SQL (transaction() 内)
- 事务 → with transaction() as conn: ...
- 上下文感知传参 (db 参数) → db=None 占位 (兼容即可)
