# 阶段五 Review 修复报告

## 本次修复

### c5c6a62 后续 review 修复

- 非 JSON、数组或 null 队列 payload 现在统一识别为 malformed，并写入 poison dead-letter，避免消息永久重试占用队列。
- poison payload 写入 JSONB 时对缺失原始值使用 `null` 兜底，保证异常消息也能完成归档。
- Cron migration 在创建 worker job 前校验 Vault 中的 worker URL 和 service key；任一缺失或为空时抛错并回滚，不再将未启用的任务标记为 completed。

- Worker 使用 `lease_token`/`lease_until` 进行条件 claim、成功和失败更新，过期租约可重新领取，旧 worker 不能覆盖已成功任务。
- Worker claim 时校验 receipt 的 `user_id`、`conversation_id`、`dedupe_key` 以及 payload 中对应字段，拒绝跨用户或篡改 payload。
- 成功状态先落库再 ack；ack/delete 失败时重复消费会识别 `succeeded` 并幂等调用 delete，不重复写入记忆。
- DashScope 请求增加 30 秒超时；候选 key/content 做 trim、长度和非空校验，confidence 归一化到 0..1。
- 异步提取同时受 `MEMORY_ASYNC_EXTRACTION_ENABLED` 与 `LONG_TERM_MEMORY_ENABLED` 控制。
- Python `MemoryJobRepository` 默认读取 `MEMORY_JOB_MAX_ATTEMPTS`，与 Edge Function 配置统一。
- turn id 改为每次回答生成随机 UUID，相同内容的不同轮次不会因哈希碰撞被去重。

## 验证数据

- `python -m pytest -q`: **54 passed, 1 skipped**。
- `python -m compileall -q .`: 通过。
- `node --check supabase/functions/memory-worker/index.ts`: 通过。
- `git diff --check`: 通过（仅提示现有 CRLF 转换警告，无 whitespace error）。

本次 P1 review 修复前的独立审查发现 2 个 P1，均已修复并以测试/静态检查复核；未发现 P0。

## 未解决风险与阻塞

- 当前环境没有 `SUPABASE_DB_URL`、Supabase CLI、Docker 或 `psql`，因此无法执行真实隔离 schema migration、pgmq 重复消费/重试/死信、RLS/越权、并发租约竞态和 P50/P95 延迟测试；本报告不把本地单测当作真实数据库验证。
- pgmq `create/read/set_vt/archive/delete` 的具体扩展版本语义仍需在真实 Supabase 项目 dry-run 验证。
- `memory-worker` 直接连接数据库的角色必须具备 `pgmq` 和 `app_private` 的最小服务端权限；当前迁移撤销了 PUBLIC/anon/authenticated 权限，尚未在真实项目验证实际连接角色授权。
- Cron migration 现在要求先配置 `memory_worker_url` 和 `memory_worker_service_key` Vault secret；部署顺序需先写入 secret，再执行 migration。
- 生产切换要求的连续 7 天错误率、P95 checkpoint 延迟和异步生效时延尚未开始采集。
- legacy 历史 read-modify-write 并发覆盖、Store filter/list 完整语义、pgvector 迁移仍属于后续阶段工作。
