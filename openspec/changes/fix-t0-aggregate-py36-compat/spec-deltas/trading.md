# Spec Delta — fix-t0-aggregate-py36-compat → trading

## MODIFIED Requirements

### REQ-TRADE-006: T0 敞口聚合 schema（注释统一）

将 schema 字段类型注释中 `list[T]` 写法统一改为 `List[T]`（typing 模块），
与 `dev-process-control` "Python 3.6.8 兼容" 约束保持一致。

示例（仅注释 / docstring）：

```
T0ExposureOut:
  positions: List[ExposurePositionOut]
  totals: ExposureTotalsOut

T0AggregateOut:
  by_day: List[AggregateByDayOut]
  by_stock: List[AggregateByStockOut]
```

无 ADDED / REMOVED Requirements。