-- #324 (SR-17, TDD-2.1.20): every qualification report a command produces is
-- a stored artifact with a typed ledger event naming its kind, so activation
-- admission reads its comparison reports from storage rather than from the
-- operator. A row is immutable: a rerun that measures again appends a row,
-- and a kind's current report is its most recently recorded one.
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
    'qualification_report_recorded'
));

CREATE TABLE IF NOT EXISTS qualification_reports (
    report_id uuid PRIMARY KEY,
    report_kind text NOT NULL CHECK (report_kind IN (
        'inference_battery', 'jev_smoke', 'retrieval', 'three_head'
    )),
    report_hash bytea NOT NULL REFERENCES artifacts(hash) ON DELETE RESTRICT
        CHECK (octet_length(report_hash) = 32),
    primary_metric text NOT NULL CHECK (length(primary_metric) BETWEEN 1 AND 128),
    registered_at timestamptz NOT NULL,
    executed_at timestamptz NOT NULL,
    ledger_sequence bigint NOT NULL UNIQUE REFERENCES ledger_records(sequence),
    CHECK (registered_at <= executed_at)
);
CREATE INDEX IF NOT EXISTS qualification_reports_kind_idx
    ON qualification_reports(report_kind, ledger_sequence DESC);

DROP TRIGGER IF EXISTS qualification_reports_immutable ON qualification_reports;
CREATE TRIGGER qualification_reports_immutable BEFORE UPDATE OR DELETE ON qualification_reports
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

INSERT INTO storage_schema_versions(version) VALUES (24) ON CONFLICT DO NOTHING;
