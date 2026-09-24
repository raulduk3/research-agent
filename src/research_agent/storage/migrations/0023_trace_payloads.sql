-- #308 (TDD-2.1.2): each trace row stores the bytes it hashes. A call row
-- points at its canonical request, a terminal row at the envelope the run
-- received, each an artifact of its own kind written by the trace route in
-- the row's transaction. A payload over the bound is stored truncated and
-- flagged, under the hash of the stored bytes. Rows recorded before this
-- migration have no payload; every row after it must have one.
DO $$
DECLARE
    check_name text;
BEGIN
    SELECT conname INTO check_name
    FROM pg_constraint
    WHERE conrelid = 'artifacts'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%tool_response%'
      AND pg_get_constraintdef(oid) NOT LIKE '%trace_response%';
    IF check_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE artifacts DROP CONSTRAINT %I', check_name);
        ALTER TABLE artifacts ADD CONSTRAINT artifacts_kind_check CHECK (kind IN (
            'source_response', 'source_document', 'extraction', 'vector_payload',
            'model_weights', 'tokenizer', 'manifest', 'tool_request',
            'tool_response', 'provider_response', 'study_evidence',
            'signature_evidence', 'trace_request', 'trace_response'
        ));
    END IF;
END $$;

ALTER TABLE run_trace_calls
    ADD COLUMN IF NOT EXISTS request_artifact bytea
        REFERENCES artifacts(hash) ON DELETE RESTRICT
        CHECK (octet_length(request_artifact) = 32),
    ADD COLUMN IF NOT EXISTS request_truncated boolean;

ALTER TABLE run_trace_terminals
    ADD COLUMN IF NOT EXISTS response_artifact bytea
        REFERENCES artifacts(hash) ON DELETE RESTRICT
        CHECK (octet_length(response_artifact) = 32),
    ADD COLUMN IF NOT EXISTS response_truncated boolean;

-- The cutoff is the moment this migration first ran, fixed into the check
-- then: a row started before it may lack its payload, none after it may.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'run_trace_calls'::regclass
          AND conname = 'run_trace_calls_request_payload_check'
    ) THEN
        EXECUTE format(
            'ALTER TABLE run_trace_calls ADD CONSTRAINT run_trace_calls_request_payload_check
             CHECK ((request_artifact IS NULL) = (request_truncated IS NULL)
                    AND (request_artifact IS NOT NULL OR started_at < %L))',
            transaction_timestamp()
        );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'run_trace_terminals'::regclass
          AND conname = 'run_trace_terminals_response_payload_check'
    ) THEN
        EXECUTE format(
            'ALTER TABLE run_trace_terminals ADD CONSTRAINT run_trace_terminals_response_payload_check
             CHECK ((response_artifact IS NULL) = (response_truncated IS NULL)
                    AND (response_artifact IS NOT NULL OR ended_at < %L))',
            transaction_timestamp()
        );
    END IF;
END $$;

INSERT INTO storage_schema_versions(version) VALUES (23) ON CONFLICT DO NOTHING;
