-- #330: what one run cost the system, recorded once by the orchestrator after
-- the run's settlement. The row holds the run's model calls (tokens, returned
-- model identity, latency, bytes each way), the endpoints it reached, its
-- process CPU and peak memory, host load at start and end, and its wall
-- clock, as canonical JSON. The token columns repeat the calls' sums so a
-- query can hold them against the settlement. Insert-only, with its ledger
-- event. Nothing here is shown to the agent.
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
    'run_settled', 'trace_call_recorded', 'trace_terminal_recorded',
    'qualification_report_recorded', 'run_resources_recorded'
));

CREATE TABLE IF NOT EXISTS run_resources (
    run_id uuid PRIMARY KEY REFERENCES run_settlements(run_id) ON DELETE RESTRICT,
    record bytea NOT NULL,
    model_calls integer NOT NULL CHECK (model_calls >= 0),
    input_tokens bigint NOT NULL CHECK (input_tokens >= 0),
    cached_input_tokens bigint NOT NULL CHECK (cached_input_tokens >= 0),
    output_tokens bigint NOT NULL CHECK (output_tokens >= 0),
    recorded_at timestamptz NOT NULL,
    ledger_sequence bigint NOT NULL REFERENCES ledger_records(sequence) ON DELETE RESTRICT
);

DROP TRIGGER IF EXISTS run_resources_immutable ON run_resources;
CREATE TRIGGER run_resources_immutable BEFORE UPDATE OR DELETE ON run_resources
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

INSERT INTO storage_schema_versions(version) VALUES (26) ON CONFLICT DO NOTHING;
