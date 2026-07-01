# frontend delta — 限价单价格支持小数

## MODIFIED Requirements

### REQ-FE-010: 委托价格输入支持小数（v8）

**Before (commit `f1695e0` 前):**
- `client/src/components/OrderForm.vue:52` 设 `:precision="null"`（限价单）
- element-plus `el-input-number` `precision=null` 被默认值 `0` 覆盖 → 输入 11.55 四舍五入为 12
- 用户报障：下单页限价单价格只接受整数，无法输入小数

**After:**
- 限价单：`:precision="2"`（A 股 0.01 元最小变动单位）
- 非限价单（市价/最新价/挂单价）：input disabled，precision 无实际作用
- 保留 `:step="0.01"` 步进

**Why:**
- element-plus `precision` 类型 `number | null`，`null` 显式无精度但被默认值 0 覆盖
- 显式 `2` 兼容 A 股价格规则（2 位小数）
- 后端 `OrderOut.price: float` 本就支持小数，无需改

## Cross-References

- 实施 commit: `f1695e0`
- 主 spec: `frontend/spec.md` REQ-FE-010
