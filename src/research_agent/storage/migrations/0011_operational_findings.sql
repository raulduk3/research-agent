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
    'operational_finding_recorded'
));

-- EN-11 (TDD-3.1.15): a pinned question naming an absent or unsupported
-- resolver build schedules a durable, append-only finding rather than
-- failing silently; the mirrored pattern is `resolutions`, one row per
-- typed condition with no update or delete path.
CREATE TABLE IF NOT EXISTS operational_findings (
    id uuid PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('resolver_unavailable')),
    pinned_registry_hash bytea NOT NULL CHECK (octet_length(pinned_registry_hash) = 32),
    detail text NOT NULL CHECK (length(detail) BETWEEN 1 AND 256),
    detected_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS operational_findings_pinned_registry_hash_idx
    ON operational_findings(pinned_registry_hash, detected_at);

DROP TRIGGER IF EXISTS operational_findings_immutable ON operational_findings;
CREATE TRIGGER operational_findings_immutable BEFORE UPDATE OR DELETE ON operational_findings
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

INSERT INTO storage_schema_versions(version) VALUES (11) ON CONFLICT DO NOTHING;
