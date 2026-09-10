-- 知识库上传者归属迁移（幂等，可重复执行）
-- 执行方式：在 Supabase SQL Editor 中执行本文件后，再部署应用代码。

BEGIN;

ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS operator TEXT;
ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS operator_id TEXT;
ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS operator_name TEXT;
ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS source_type TEXT DEFAULT 'user';

-- 预置知识的归属固定为系统运营者“小曹”。
UPDATE kb_documents
SET source_type = 'seed',
    operator_id = 'system',
    operator_name = '小曹',
    operator = '小曹'
WHERE source_type = 'seed'
   OR source LIKE '[种子] %';

-- 可关联到用户的历史上传记录恢复为实际用户名。
UPDATE kb_documents AS k
SET source_type = 'user',
    operator_id = k.user_id,
    operator_name = u.username,
    operator = u.username
FROM users AS u
WHERE k.user_id = u.id
  AND COALESCE(k.source_type, 'user') <> 'seed'
  AND COALESCE(k.source, '') NOT LIKE '[种子] %';

-- 用户已删除或历史数据无法关联时，保留真实 user_id 并明确标记。
UPDATE kb_documents
SET source_type = 'user',
    operator_id = COALESCE(NULLIF(operator_id, ''), user_id),
    operator_name = COALESCE(NULLIF(operator_name, ''), '历史用户'),
    operator = COALESCE(NULLIF(operator_name, ''), '历史用户')
WHERE COALESCE(source_type, 'user') <> 'seed'
  AND COALESCE(source, '') NOT LIKE '[种子] %'
  AND NOT EXISTS (SELECT 1 FROM users WHERE users.id = kb_documents.user_id);

COMMIT;
