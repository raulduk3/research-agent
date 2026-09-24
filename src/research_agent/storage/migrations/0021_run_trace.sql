-- #297 (TDD-2.1.2, TDD-2.1.36): the tool service records each call a run
-- makes before executing it. A call row allocates the run's next call
-- sequence and holds the request hash and schema decision; a refused call is
-- a row too, with its reason, and is already resolved. An admitted call is
-- resolved by one terminal row, a response or an error. Both tables are
-- immutable: a terminal is appended beside its request, never written into
-- it. Each row commits with its own ledger event.
DO $$
DECLARE
    check_name text;
BEGIN
    SELECT conname INTO check_name
    FROM pg_constraint
    WHERE conrelid = 'ledger_records'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%event_kind%';
    IF check_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE ledger_records DROP CONSTRAINT %I', check_name);
    END IF;
END $$;

ALTER TABLE ledger_records ADD CONSTRAINT ledger_records_event_kind_check CHECK (event_kind IN (
    'artifact_committed', 'paper_observed', 'job_transition', 'snapshot_sealed',
    'snapshot_items_pinned', 'sheet_sealed', 'run_created', 'run_event',
    'submission_accepted', 'submission_rejected', 'bundle_activated', 'digest_created',
    'rating_recorded', 'rater_provisioned', 'human_forecast_sealed', 'alert_acknowledged',
    'spend_reserved', 'spend_reconciled', 'study_imported', 'anchor_received',
    'score_published', 'run_budget_reserved', 'run_budget_reconciled', 'resolution_recorded',
    'operational_finding_recorded', 'genome_admitted', 'genome_archived',
    'owner_provisioned', 'genome_owner_admission_recorded', 'genome_retirement_requested',
    'preference_credit_recorded', 'preference_credit_gap_recorded',
    'exclusion_action_recorded', 'paper_requested', 'run_voided', 'paper_request_transitioned',
    'run_settled', 'trace_call_recorded', 'trace_terminal_recorded'
));

CREATE TABLE IF NOT EXISTS run_trace_calls (
    run_id uuid NOT NULL REFERENCES runs(id) ON DELETE RESTRICT,
    call_sequence integer NOT NULL CHECK (call_sequence > 0),
    call_id uuid NOT NULL UNIQUE,
    tool text NOT NULL CHECK (length(tool) BETWEEN 1 AND 64),
    request_hash bytea NOT NULL CHECK (octet_length(request_hash) = 32),
    decision text NOT NULL CHECK (decision IN ('admitted', 'refused')),
    reason text CHECK (reason IS NULL OR length(reason) BETWEEN 1 AND 128),
    started_at timestamptz NOT NULL,
    ledger_sequence bigint NOT NULL REFERENCES ledger_records(sequence) ON DELETE RESTRICT,
    PRIMARY KEY(run_id, call_sequence),
    CHECK ((decision = 'refused') = (reason IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS run_trace_terminals (
    run_id uuid NOT NULL,
    call_sequence integer NOT NULL,
    outcome text NOT NULL CHECK (outcome IN ('response', 'error')),
    response_hash bytea NOT NULL CHECK (octet_length(response_hash) = 32),
    error_code text CHECK (error_code IS NULL OR length(error_code) BETWEEN 1 AND 128),
    retrieved_ids bytea[] NOT NULL CHECK (cardinality(retrieved_ids) <= 100),
    budget_deltas bytea NOT NULL,
    ended_at timestamptz NOT NULL,
    ledger_sequence bigint NOT NULL REFERENCES ledger_records(sequence) ON DELETE RESTRICT,
    PRIMARY KEY(run_id, call_sequence),
    FOREIGN KEY(run_id, call_sequence)
        REFERENCES run_trace_calls(run_id, call_sequence) ON DELETE RESTRICT,
    CHECK ((outcome = 'error') = (error_code IS NOT NULL)),
    CHECK (outcome = 'response' OR cardinality(retrieved_ids) = 0)
);

DROP TRIGGER IF EXISTS run_trace_calls_immutable ON run_trace_calls;
CREATE TRIGGER run_trace_calls_immutable BEFORE UPDATE OR DELETE ON run_trace_calls
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

DROP TRIGGER IF EXISTS run_trace_terminals_immutable ON run_trace_terminals;
CREATE TRIGGER run_trace_terminals_immutable BEFORE UPDATE OR DELETE ON run_trace_terminals
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

INSERT INTO storage_schema_versions(version) VALUES (21) ON CONFLICT DO NOTHING;
