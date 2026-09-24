-- Decision 0031, #300: the ask tool.
--
-- A run's allowed tools admit `ask` as a sixth name. The UTC day's Jev usage
-- row carries the ask pool's reserved spend beside the day's total, so an ask
-- is checked against the pool and the whole Jev sublimit in the one atomic
-- update that already counts card attempts; an ask reservation is marked so,
-- and settles exactly as a card attempt does. Each answered ask is kept once
-- per run and work key: the run's count of them is its ask budget as the
-- tool service sees it, and a replayed call is served the kept answer
-- without reaching Jev again.
DO $$
DECLARE
    check_name text;
BEGIN
    FOR check_name IN
        SELECT conname FROM pg_constraint
        WHERE conrelid = 'runs'::regclass AND contype = 'c'
          AND pg_get_constraintdef(oid) LIKE '%allowed_tools%'
    LOOP
        EXECUTE format('ALTER TABLE runs DROP CONSTRAINT %I', check_name);
    END LOOP;
END $$;
ALTER TABLE runs ADD CONSTRAINT runs_allowed_tools_check CHECK (
    array_length(allowed_tools, 1) BETWEEN 1 AND 6
    AND allowed_tools <@ ARRAY[
        'query_cards', 'neighbors', 'graph', 'deep_read', 'ask', 'submit'
    ]
);

ALTER TABLE jev_daily_usage
    ADD COLUMN IF NOT EXISTS ask_reserved_micros bigint NOT NULL DEFAULT 0
        CHECK (ask_reserved_micros >= 0);

ALTER TABLE jev_attempt_reservations
    ADD COLUMN IF NOT EXISTS purpose text NOT NULL DEFAULT 'card'
        CHECK (purpose IN ('card', 'ask'));

CREATE TABLE IF NOT EXISTS jev_ask_answers (
    run_id uuid NOT NULL REFERENCES runs(id) ON DELETE RESTRICT,
    work_key bytea NOT NULL CHECK (octet_length(work_key) = 32),
    answer bytea NOT NULL CHECK (octet_length(answer) BETWEEN 1 AND 65536),
    answered_at timestamptz NOT NULL,
    PRIMARY KEY(run_id, work_key)
);

DROP TRIGGER IF EXISTS jev_ask_answers_immutable ON jev_ask_answers;
CREATE TRIGGER jev_ask_answers_immutable
BEFORE UPDATE OR DELETE ON jev_ask_answers
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

INSERT INTO storage_schema_versions(version) VALUES (25) ON CONFLICT DO NOTHING;
