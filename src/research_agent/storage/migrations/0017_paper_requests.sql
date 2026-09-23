-- Decision 0025: a deep_read or graph call naming a family the run's snapshot
-- does not hold records a paper request. The request is a row, not a fetch:
-- the acquisition side reads open rows under the ingest role and moves them
-- to acquiring, then acquired or failed with the reason. A family has at most
-- one request that has not failed, so a second ask records nothing.
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
    'exclusion_action_recorded', 'paper_requested'
));

CREATE TABLE IF NOT EXISTS paper_requests (
    id uuid PRIMARY KEY,
    family_id uuid NOT NULL,
    run_id uuid NOT NULL REFERENCES runs(id) ON DELETE RESTRICT,
    snapshot_hash bytea NOT NULL REFERENCES snapshots(hash) ON DELETE RESTRICT
        CHECK (octet_length(snapshot_hash) = 32),
    requested_at timestamptz NOT NULL,
    status text NOT NULL CHECK (status IN ('requested', 'acquiring', 'acquired', 'failed')),
    reason text CHECK (reason IS NULL OR length(reason) BETWEEN 1 AND 512),
    ledger_sequence bigint NOT NULL UNIQUE
        REFERENCES ledger_records(sequence) ON DELETE RESTRICT,
    CHECK ((status = 'failed') = (reason IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS paper_requests_one_unfailed_per_family
    ON paper_requests(family_id) WHERE status <> 'failed';
CREATE INDEX IF NOT EXISTS paper_requests_run_idx ON paper_requests(run_id);
CREATE INDEX IF NOT EXISTS paper_requests_open_idx
    ON paper_requests(requested_at, id) WHERE status IN ('requested', 'acquiring');

INSERT INTO storage_schema_versions(version) VALUES (17) ON CONFLICT DO NOTHING;
