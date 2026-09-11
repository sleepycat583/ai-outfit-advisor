-- Repair the first compatibility backfill so legacy rows cannot re-introduce
-- an unbounded transcript into the Agent context.  The UI keeps `messages`
-- untouched; only the Agent-facing `recent_messages` window is rebuilt.

BEGIN;

DO $$
DECLARE
    chat_row RECORD;
    all_messages JSONB;
    bounded_messages JSONB;
BEGIN
    FOR chat_row IN
        SELECT session_id, messages
        FROM public.chat_messages
    LOOP
        BEGIN
            all_messages := COALESCE(NULLIF(chat_row.messages, ''), '[]')::JSONB;
            IF jsonb_typeof(all_messages) <> 'array' THEN
                all_messages := '[]'::JSONB;
            END IF;

            SELECT COALESCE(jsonb_agg(item ORDER BY ordinal), '[]'::JSONB)
            INTO bounded_messages
            FROM (
                SELECT item, ordinal
                FROM jsonb_array_elements(all_messages) WITH ORDINALITY AS entries(item, ordinal)
                ORDER BY ordinal DESC
                LIMIT 20
            ) AS tail;

            UPDATE public.chat_messages
            SET recent_messages = bounded_messages::TEXT,
                summary = COALESCE(summary, ''),
                summary_message_count = COALESCE(summary_message_count, 0)
            WHERE session_id = chat_row.session_id;
        EXCEPTION WHEN OTHERS THEN
            -- A malformed legacy transcript must not abort the whole migration.
            UPDATE public.chat_messages
            SET recent_messages = '[]',
                summary = COALESCE(summary, ''),
                summary_message_count = COALESCE(summary_message_count, 0)
            WHERE session_id = chat_row.session_id;
        END;
    END LOOP;
END
$$;

COMMIT;
