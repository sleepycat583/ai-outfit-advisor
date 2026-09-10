-- Legacy chat memory compatibility migration.
-- The application keeps the complete transcript for UI recovery, while Agent
-- context uses summary + recent_messages to stay within the context budget.

BEGIN;

ALTER TABLE public.chat_messages
    ADD COLUMN IF NOT EXISTS recent_messages TEXT;

ALTER TABLE public.chat_messages
    ADD COLUMN IF NOT EXISTS summary TEXT;

ALTER TABLE public.chat_messages
    ADD COLUMN IF NOT EXISTS summary_message_count INTEGER;

UPDATE public.chat_messages
SET
    recent_messages = COALESCE(NULLIF(recent_messages, ''), messages, '[]'),
    summary = COALESCE(summary, ''),
    summary_message_count = COALESCE(summary_message_count, 0);

ALTER TABLE public.chat_messages
    ALTER COLUMN recent_messages SET DEFAULT '[]',
    ALTER COLUMN recent_messages SET NOT NULL,
    ALTER COLUMN summary SET DEFAULT '',
    ALTER COLUMN summary SET NOT NULL,
    ALTER COLUMN summary_message_count SET DEFAULT 0,
    ALTER COLUMN summary_message_count SET NOT NULL;

COMMIT;
