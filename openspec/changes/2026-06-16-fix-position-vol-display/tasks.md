# Tasks: Fix position `vol` not showing in Position.vue

- [ ] 1. `server/services/push_handlers.py:handle_pos_cfm`: vol 字段兜底（缺/为 0 时用 avl_vol）
- [ ] 2. `server/services/push_handlers.py:handle_pos_cfm`: 加注释说明 vol/avl_vol 字段映射
- [ ] 3. `server/test_push_handlers.py`: 加 3 个测试用例（缺字段 / 完整 / 全 0）
- [ ] 4. `pytest server/test_push_handlers.py -v` 全绿
- [ ] 5. `pytest server/ -v` 全绿（确保无回归）
- [ ] 6. 手动验证：登录后 Position.vue 总持仓列正常显示（持仓 > 0 时）
- [ ] 7. 提交：`fix(push): pos_cfm vol 字段缺时兜底为 avl_vol`
- [ ] 8. 归档：spec 已合并后 `mv openspec/changes/2026-06-16-fix-position-vol-display openspec/changes/archive/`
