-- 2026-08-09-cleanup-old-scripts-and-seed-demo.sql
-- change `2026-08-09-strategy-exec-service` Phase 5: 清理旧用户脚本 + 插入新 Backtrader demo

-- ⚠️ BACKUP 提醒: 跑之前先 dump
--   mysqldump -h 192.168.10.2 -P 33066 -u EvTrade -p evtrade strategy_script > backup_strategy_script_20260809.sql

-- ──────────────── 步骤 1: 删旧脚本 (5 个) ────────────────
-- 删除 v90 时代用户自写脚本 (策略引擎改用 Backtrader, 这些脚本接口不兼容)
DELETE FROM strategy_script WHERE name IN ('ma5_e2e', 'test1', 'ma5_test', 'TEST', 'v90test');

-- ──────────────── 步骤 2: 插入新 demo 脚本 (mas_v1) ────────────────
-- 幂等: 仅在 (user_id=6, id='mas_v1') 不存在时插入
INSERT INTO strategy_script
    (id, user_id, name, code, params_schema, description, status, is_public, created_at, updated_at)
SELECT
    'mas_v1' AS id,
    6 AS user_id,
    'mas_v1' AS name,
    :code AS code,
    :params_schema AS params_schema,
    :description AS description,
    'active' AS status,
    1 AS is_public,
    NOW() AS created_at,
    NOW() AS updated_at
FROM DUAL
WHERE NOT EXISTS (
    SELECT 1 FROM strategy_script WHERE user_id = 6 AND id = 'mas_v1'
);

-- ──────────────── 步骤 3: 验证 ────────────────
SELECT id, user_id, name, status, is_public, LENGTH(code) AS code_len
  FROM strategy_script
 ORDER BY user_id, id;