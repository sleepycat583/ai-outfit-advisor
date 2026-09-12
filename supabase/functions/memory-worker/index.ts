import postgres from "npm:postgres@3.4.8";

const queueName = Deno.env.get("MEMORY_JOB_QUEUE_NAME") ?? "memory-extraction";
const databaseUrl = Deno.env.get("SUPABASE_DB_URL");
const dashscopeKey = Deno.env.get("DASHSCOPE_API_KEY");
const workerKey = Deno.env.get("MEMORY_WORKER_SERVICE_KEY");
const maxAttempts = Number(Deno.env.get("MEMORY_JOB_MAX_ATTEMPTS") ?? "5");

type QueueMessage = {
  msg_id: number;
  read_ct: number;
  message: string | Record<string, unknown>;
};

type Candidate = {
  key: string;
  content: string;
  confidence?: number;
};

function authorized(request: Request): boolean {
  return Boolean(workerKey) && request.headers.get("authorization") === `Bearer ${workerKey}`;
}

function parseMessage(message: QueueMessage["message"]): Record<string, unknown> {
  return typeof message === "string" ? JSON.parse(message) : message;
}

async function sha256(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest)).map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function extractCandidates(job: Record<string, unknown>): Promise<Candidate[]> {
  if (!dashscopeKey) throw new Error("DASHSCOPE_API_KEY is not configured");
  const messages = Array.isArray(job.messages) ? job.messages : [];
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30_000);
  let response: Response;
  try {
    response = await fetch("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", {
    method: "POST",
    headers: {
      "authorization": `Bearer ${dashscopeKey}`,
      "content-type": "application/json",
    },
      signal: controller.signal,
      body: JSON.stringify({
      model: Deno.env.get("MEMORY_EXTRACTION_MODEL") ?? "qwen-plus",
      temperature: 0,
      messages: [
        {
          role: "system",
          content: "从对话中提取稳定、可复用的用户穿搭偏好。只返回 JSON 数组，每项为 {key, content, confidence}。忽略一次性天气、闲聊和助手臆测；不要提取敏感身份信息。",
        },
        { role: "user", content: JSON.stringify(messages) },
      ],
      response_format: { type: "json_object" },
      }),
    });
  } finally {
    clearTimeout(timeout);
  }
  if (!response.ok) throw new Error(`DashScope HTTP ${response.status}`);
  const payload = await response.json();
  const content = payload?.choices?.[0]?.message?.content;
  const parsed = typeof content === "string" ? JSON.parse(content) : content;
  const candidates = Array.isArray(parsed) ? parsed : parsed?.memories;
  if (!Array.isArray(candidates)) return [];
  return candidates
    .filter((item): item is Candidate => Boolean(item && typeof item.key === "string" && typeof item.content === "string"))
    .map((item) => ({
      key: item.key.trim().slice(0, 120),
      content: item.content.trim().slice(0, 2000),
      confidence: typeof item.confidence === "number" && Number.isFinite(item.confidence)
        ? Math.max(0, Math.min(1, item.confidence))
        : null,
    }))
    .filter((item) => item.key.length > 0 && item.content.length > 0);
}

async function recordFailure(
  sql: ReturnType<typeof postgres>,
  message: QueueMessage,
  jobId: string,
  error: unknown,
  leaseToken = "",
  expected?: { userId: string; conversationId: string; dedupeKey: string },
): Promise<void> {
  const messageText = String(error).slice(0, 2000);
  const attempt = Number(message.read_ct ?? 1);
  const dead = attempt >= maxAttempts;
  await sql.begin(async (transaction) => {
    if (jobId) {
      const succeeded = await transaction`
        SELECT status FROM app_private.memory_job_receipts
        WHERE job_id = ${jobId}
      `;
      if (succeeded[0]?.status === "succeeded") {
        // Crash after the success transition must be recoverable: deleting an
        // already-deleted pgmq message is intentionally idempotent.
        await transaction`SELECT pgmq.delete(${queueName}, ${message.msg_id})`;
        return;
      }
      const tokenClause = leaseToken
        ? transaction`AND lease_token = ${leaseToken} AND status = 'processing'`
        : expected
          ? transaction`AND user_id = ${expected.userId} AND conversation_id = ${expected.conversationId} AND dedupe_key = ${expected.dedupeKey} AND status <> 'succeeded'`
          : transaction`AND status <> 'succeeded'`;
      await transaction`
        UPDATE app_private.memory_job_receipts
        SET status = ${dead ? "dead_letter" : "retrying"}, last_error = ${messageText}, attempts = ${attempt}, lease_token = NULL, lease_until = NULL, updated_at = now()
        WHERE job_id = ${jobId} ${tokenClause}
      `;
    }
    if (dead) {
      await transaction`SELECT pgmq.archive(${queueName}, ${message.msg_id})`;
      if (jobId) {
        await transaction`
          INSERT INTO app_private.memory_dead_letters (job_id, msg_id, error, attempts)
          VALUES (${jobId}, ${message.msg_id}, ${messageText}, ${attempt})
          ON CONFLICT (job_id) DO UPDATE SET error = EXCLUDED.error, attempts = EXCLUDED.attempts, updated_at = now()
        `;
      }
    } else {
      const delay = Math.min(900, 15 * (2 ** Math.max(0, attempt - 1)));
      await transaction`SELECT pgmq.set_vt(${queueName}, ${message.msg_id}, ${delay})`;
    }
  });
}

async function processMessage(sql: ReturnType<typeof postgres>, message: QueueMessage): Promise<void> {
  const attempt = Number(message.read_ct ?? 1);
  let jobId = "";
  let leaseToken = "";
  let expected = { userId: "", conversationId: "", dedupeKey: "" };

  try {
    const job = parseMessage(message.message);
    jobId = String(job.job_id ?? "");
    const dedupeKey = String(job.dedupe_key ?? "");
    const userId = String(job.user_id ?? "");
    const conversationId = String(job.conversation_id ?? "");
    expected = { userId, conversationId, dedupeKey };
    if (!jobId || !dedupeKey || !userId || !conversationId) throw new Error("invalid memory extraction payload");
    leaseToken = crypto.randomUUID();

    const claimed = await sql.begin(async (transaction) => transaction`
      UPDATE app_private.memory_job_receipts
      SET status = 'processing', attempts = ${attempt}, lease_token = ${leaseToken}, lease_until = now() + interval '180 seconds', updated_at = now()
      WHERE job_id = ${jobId}
        AND user_id = ${userId} AND conversation_id = ${conversationId} AND dedupe_key = ${dedupeKey}
        AND payload->>'user_id' = ${userId}
        AND payload->>'conversation_id' = ${conversationId}
        AND payload->>'dedupe_key' = ${dedupeKey}
        AND status <> 'succeeded'
        AND (status <> 'processing' OR lease_until IS NULL OR lease_until < now())
      RETURNING job_id, lease_token
    `);
    if (claimed.length === 0) return;

    const candidates = await extractCandidates(job);
    for (const candidate of candidates) {
      const itemKey = `auto:${await sha256(`${dedupeKey}\x1f${candidate.key}`)}`;
      await sql`
        INSERT INTO app_private.memory_items (namespace, key, value)
        VALUES (${sql.array([`user:${userId}`, "memory"])}, ${itemKey}, ${sql.json({
          content: candidate.content,
          source: "async_extraction",
          confidence: candidate.confidence ?? null,
          dedupe_key: dedupeKey,
        })})
        ON CONFLICT (namespace, key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
      `;
    }
    const completed = await sql`
      UPDATE app_private.memory_job_receipts
      SET status = 'succeeded', completed_at = now(), lease_token = NULL, lease_until = NULL, updated_at = now(), last_error = NULL
      WHERE job_id = ${jobId} AND lease_token = ${leaseToken} AND status = 'processing'
      RETURNING job_id
    `;
    if (completed.length === 0) return;
    await sql`SELECT pgmq.delete(${queueName}, ${message.msg_id})`;
  } catch (error) {
    await recordFailure(sql, message, jobId, error, leaseToken, expected);
  }
}

Deno.serve(async (request) => {
  if (request.method !== "POST" || !authorized(request)) {
    return new Response("unauthorized", { status: 401 });
  }
  if (!databaseUrl) return new Response("SUPABASE_DB_URL is not configured", { status: 500 });

  const sql = postgres(databaseUrl, { max: 2, ssl: "require" });
  try {
    const messages = await sql<QueueMessage[]>`SELECT * FROM pgmq.read(${queueName}, 120, 10)`;
    for (const message of messages) await processMessage(sql, message);
    return Response.json({ claimed: messages.length });
  } finally {
    await sql.end({ timeout: 5 });
  }
});
