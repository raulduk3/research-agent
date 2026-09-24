-- Decision 0025, acquisition side: a paper request moves requested ->
-- acquiring -> acquired | failed(reason), or requested -> refused(reason)
-- when a budget turns it away. Both the per-run cap and the per-day
-- acquisition budget record a refused row, so a refusal is visible rather
-- than silent. A request is open, and unique per family, only while it is
-- requested or acquiring; acquired names the paper version it produced, and
-- started_at is when acquisition began, which the day's budget counts.
-- Every transition is one ledger event.
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
    'exclusion_action_recorded', 'paper_requested', 'run_voided', 'paper_request_transitioned'
));

DO $$
DECLARE
    check_name text;
BEGIN
    FOR check_name IN
        SELECT conname FROM pg_constraint
        WHERE conrelid = 'paper_requests'::regclass AND contype = 'c'
          AND (pg_get_constraintdef(oid) LIKE '%status%')
    LOOP
        EXECUTE format('ALTER TABLE paper_requests DROP CONSTRAINT %I', check_name);
    END LOOP;
END $$;

ALTER TABLE paper_requests
    ADD COLUMN IF NOT EXISTS started_at timestamptz,
    ADD COLUMN IF NOT EXISTS paper_version_id uuid,
    ADD COLUMN IF NOT EXISTS last_ledger_sequence bigint
        REFERENCES ledger_records(sequence) ON DELETE RESTRICT;
UPDATE paper_requests SET last_ledger_sequence = ledger_sequence
    WHERE last_ledger_sequence IS NULL;
UPDATE paper_requests SET started_at = requested_at
    WHERE started_at IS NULL AND status IN ('acquiring', 'acquired', 'failed');
ALTER TABLE paper_requests ALTER COLUMN last_ledger_sequence SET NOT NULL;

ALTER TABLE paper_requests ADD CONSTRAINT paper_requests_status_check CHECK (
    status IN ('requested', 'acquiring', 'acquired', 'failed', 'refused')
);
ALTER TABLE paper_requests ADD CONSTRAINT paper_requests_reason_status_check CHECK (
    (status IN ('failed', 'refused')) = (reason IS NOT NULL)
);
ALTER TABLE paper_requests ADD CONSTRAINT paper_requests_acquired_check CHECK (
    (status = 'acquired') = (paper_version_id IS NOT NULL)
);
ALTER TABLE paper_requests ADD CONSTRAINT paper_requests_started_check CHECK (
    (status IN ('acquiring', 'acquired', 'failed')) = (started_at IS NOT NULL)
);

-- The index keeps 0017's name so that replaying 0017 finds it present and
-- does not rebuild the narrower predicate over refused rows.
DO $$
BEGIN
    IF coalesce(
        pg_get_indexdef(to_regclass('paper_requests_one_unfailed_per_family')), ''
    ) NOT LIKE '%acquiring%' THEN
        DROP INDEX IF EXISTS paper_requests_one_unfailed_per_family;
        CREATE UNIQUE INDEX paper_requests_one_unfailed_per_family
            ON paper_requests(family_id) WHERE status IN ('requested', 'acquiring');
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS paper_requests_started_idx
    ON paper_requests(started_at) WHERE started_at IS NOT NULL;

INSERT INTO storage_schema_versions(version) VALUES (19) ON CONFLICT DO NOTHING;
