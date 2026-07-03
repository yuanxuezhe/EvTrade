-- ============================================================
-- add-manual-adjust-and-history-pages (v12)
-- Migration: drop Position.today_buy / Position.today_sell
--
-- 死字段（v5 schema-refactor 以来从 do_reconcile 写入后无人读，pos_cfm 不写、
-- trd_cfm 不增量、前端部分组件消费但语义可由 Trade 表 SUM 替代）
--
-- Dev 期: rm server/evtrade.db 后 init_and_seed() 自动用新 schema 重生
-- Prod 期: 应用此脚本（一次维护窗口内执行）
--
-- 回退: ALTER TABLE positions ADD COLUMN today_buy INTEGER NOT NULL DEFAULT 0;
--       ALTER TABLE positions ADD COLUMN today_sell INTEGER NOT NULL DEFAULT 0;
-- ============================================================

-- 验证旧 column 存在（do_reconcile 注入的数据已散落, 但仍保留 metadata）
-- 失败则 skip（已无此列）
BEGIN;

ALTER TABLE positions DROP COLUMN today_buy;
ALTER TABLE positions DROP COLUMN today_sell;

COMMIT;

-- 校验
-- SELECT sql FROM sqlite_master WHERE type='table' AND name='positions';
-- 期望: 不含 today_buy / today_sell 列
