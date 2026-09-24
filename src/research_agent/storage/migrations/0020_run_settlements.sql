-- #251: one settlement per run, written when the run ends however it ended.
-- It records the tokens the loop received and whether the provider's usage
-- records or the loop's own counts supplied them. cost_micros stays null
-- until a price quote owner exists (TDD Spending authorization); the owner's
-- cost read sums only priced rows and reports unpriced tokens beside them.
-- The row is immutable and commits with its `run_settled` ledger event.
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
    'run_settled'
));

CREATE TABLE IF NOT EXISTS run_settlements (
    run_id uuid PRIMARY KEY REFERENCES runs(id) ON DELETE RESTRICT,
    provider text NOT NULL CHECK (length(provider) BETWEEN 1 AND 128),
    model text NOT NULL CHECK (length(model) BETWEEN 1 AND 128),
    input_tokens bigint NOT NULL CHECK (input_tokens >= 0),
    output_tokens bigint NOT NULL CHECK (output_tokens >= 0),
    usage_source text NOT NULL CHECK (usage_source IN ('provider', 'loop_count')),
    cost_micros bigint CHECK (cost_micros IS NULL OR cost_micros >= 0),
    settled_at timestamptz NOT NULL,
    ledger_sequence bigint NOT NULL REFERENCES ledger_records(sequence) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS run_settlements_settled_at_idx ON run_settlements(settled_at);

DROP TRIGGER IF EXISTS run_settlements_immutable ON run_settlements;
CREATE TRIGGER run_settlements_immutable BEFORE UPDATE OR DELETE ON run_settlements
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

INSERT INTO storage_schema_versions(version) VALUES (20) ON CONFLICT DO NOTHING;
