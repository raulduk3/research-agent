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
    'score_published', 'run_budget_reserved', 'run_budget_reconciled', 'resolution_recorded'
));

-- EN-04, EN-08 (TDD-3.1.8, TDD-3.1.12): append-only settlement state. A
-- resolution never updates another; a correction appends a new row naming
-- the resolution it supersedes. The resolver identity columns are the
-- complete tuple a question's first resolution pins and every later
-- resolution for the same forecast must reproduce exactly.
CREATE TABLE IF NOT EXISTS resolutions (
    id uuid PRIMARY KEY,
    forecast_id uuid NOT NULL REFERENCES submissions(id) ON DELETE RESTRICT,
    question_id uuid NOT NULL,
    resolver_id text NOT NULL CHECK (length(resolver_id) BETWEEN 1 AND 128),
    resolver_build_digest bytea NOT NULL CHECK (octet_length(resolver_build_digest) = 32),
    target_definition_hash bytea NOT NULL CHECK (octet_length(target_definition_hash) = 32),
    observation_protocol_version integer NOT NULL CHECK (observation_protocol_version >= 1),
    observation_hash bytea NOT NULL CHECK (octet_length(observation_hash) = 32),
    status text NOT NULL CHECK (status IN ('true', 'false', 'unresolvable')),
    resolution_version integer NOT NULL CHECK (resolution_version >= 1),
    supersedes_resolution_id uuid REFERENCES resolutions(id) ON DELETE RESTRICT,
    request_hash bytea NOT NULL CHECK (octet_length(request_hash) = 32),
    resolved_at timestamptz NOT NULL,
    CHECK ((resolution_version = 1) = (supersedes_resolution_id IS NULL)),
    UNIQUE(forecast_id, resolution_version)
);
CREATE INDEX IF NOT EXISTS resolutions_question_id_idx
    ON resolutions(question_id, resolution_version);

DROP TRIGGER IF EXISTS resolutions_immutable ON resolutions;
CREATE TRIGGER resolutions_immutable BEFORE UPDATE OR DELETE ON resolutions
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

INSERT INTO storage_schema_versions(version) VALUES (10) ON CONFLICT DO NOTHING;
