CREATE TABLE IF NOT EXISTS rater_principals (
    rater_id uuid PRIMARY KEY,
    island text NOT NULL CHECK (island IN ('cs', 'quant_ph')),
    salt bytea NOT NULL CHECK (octet_length(salt) = 16),
    credential_hash bytea NOT NULL CHECK (octet_length(credential_hash) = 32),
    provisioned_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(island)
);

DROP TRIGGER IF EXISTS rater_principals_immutable ON rater_principals;
CREATE TRIGGER rater_principals_immutable BEFORE UPDATE OR DELETE ON rater_principals
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

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
    'score_published', 'run_budget_reserved', 'run_budget_reconciled'
));

INSERT INTO storage_schema_versions(version) VALUES (7) ON CONFLICT DO NOTHING;
