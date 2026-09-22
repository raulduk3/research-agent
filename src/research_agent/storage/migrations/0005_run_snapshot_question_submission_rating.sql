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
    'sheet_sealed', 'run_created', 'run_event', 'submission_accepted',
    'submission_rejected', 'bundle_activated', 'digest_created', 'rating_recorded',
    'human_forecast_sealed', 'alert_acknowledged', 'spend_reserved',
    'spend_reconciled', 'study_imported', 'anchor_received', 'score_published',
    'run_budget_reserved', 'run_budget_reconciled'
));

CREATE TABLE IF NOT EXISTS snapshots (
    hash bytea PRIMARY KEY CHECK (octet_length(hash) = 32),
    paper_manifest_hash bytea NOT NULL REFERENCES artifacts(hash) ON DELETE RESTRICT
        CHECK (octet_length(paper_manifest_hash) = 32),
    sealed_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshot_indexes (
    snapshot_hash bytea NOT NULL REFERENCES snapshots(hash) ON DELETE RESTRICT,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    index_hash bytea NOT NULL CHECK (octet_length(index_hash) = 32),
    PRIMARY KEY(snapshot_hash, ordinal),
    UNIQUE(snapshot_hash, index_hash)
);

CREATE TABLE IF NOT EXISTS sheets (
    hash bytea PRIMARY KEY CHECK (octet_length(hash) = 32),
    sealed_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS sheet_questions (
    sheet_hash bytea NOT NULL REFERENCES sheets(hash) ON DELETE RESTRICT,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    question_id uuid NOT NULL,
    target_definition_hash bytea NOT NULL CHECK (octet_length(target_definition_hash) = 32),
    resolver_id text NOT NULL CHECK (length(resolver_id) BETWEEN 1 AND 128),
    resolver_version integer NOT NULL CHECK (resolver_version >= 0),
    horizon timestamptz NOT NULL,
    PRIMARY KEY(sheet_hash, ordinal),
    UNIQUE(sheet_hash, question_id)
);

CREATE TABLE IF NOT EXISTS runs (
    id uuid PRIMARY KEY,
    batch_id bytea NOT NULL REFERENCES sheets(hash) ON DELETE RESTRICT
        CHECK (octet_length(batch_id) = 32),
    shard_id text NOT NULL CHECK (length(shard_id) BETWEEN 1 AND 128),
    configuration_id uuid NOT NULL,
    attempt integer NOT NULL CHECK (attempt >= 0),
    genome_hash bytea NOT NULL CHECK (octet_length(genome_hash) = 32),
    seed bigint NOT NULL CHECK (seed >= 0),
    snapshot_hash bytea NOT NULL REFERENCES snapshots(hash) ON DELETE RESTRICT
        CHECK (octet_length(snapshot_hash) = 32),
    budgets bytea NOT NULL,
    allowed_tools text[] NOT NULL CHECK (
        array_length(allowed_tools, 1) BETWEEN 1 AND 5
        AND allowed_tools <@ ARRAY['query_cards', 'neighbors', 'graph', 'deep_read', 'submit']
    ),
    model_identity bytea NOT NULL,
    checkpoint_dates bytea NOT NULL,
    created_at timestamptz NOT NULL,
    UNIQUE(batch_id, shard_id, configuration_id, attempt)
);
CREATE INDEX IF NOT EXISTS runs_snapshot_hash_idx ON runs(snapshot_hash);

CREATE TABLE IF NOT EXISTS run_events (
    run_id uuid NOT NULL REFERENCES runs(id) ON DELETE RESTRICT,
    attempt integer NOT NULL CHECK (attempt > 0),
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    kind text NOT NULL CHECK (kind IN ('request', 'response')),
    payload_hash bytea NOT NULL CHECK (octet_length(payload_hash) = 32),
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY(run_id, attempt, ordinal)
);

CREATE TABLE IF NOT EXISTS submissions (
    id uuid PRIMARY KEY,
    sheet_hash bytea NOT NULL REFERENCES sheets(hash) ON DELETE RESTRICT
        CHECK (octet_length(sheet_hash) = 32),
    submitter_id uuid NOT NULL,
    question_id uuid NOT NULL,
    status text NOT NULL CHECK (status IN ('sealed', 'void')),
    confidence double precision CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    horizon timestamptz,
    reason text CHECK (reason IS NULL OR length(reason) BETWEEN 1 AND 512),
    sealed_at timestamptz NOT NULL,
    CHECK ((status = 'sealed') = (confidence IS NOT NULL AND horizon IS NOT NULL)),
    CHECK ((status = 'void') = (reason IS NOT NULL)),
    UNIQUE(sheet_hash, submitter_id, question_id)
);

CREATE TABLE IF NOT EXISTS submission_evidence (
    submission_id uuid NOT NULL REFERENCES submissions(id) ON DELETE RESTRICT,
    ordinal integer NOT NULL CHECK (ordinal >= 0 AND ordinal < 5),
    evidence_hash bytea NOT NULL CHECK (octet_length(evidence_hash) = 32),
    PRIMARY KEY(submission_id, ordinal)
);

CREATE TABLE IF NOT EXISTS ratings (
    id uuid PRIMARY KEY,
    rater_id uuid NOT NULL,
    paper_hash bytea NOT NULL CHECK (octet_length(paper_hash) = 32),
    digest_entry_id uuid NOT NULL,
    value text NOT NULL CHECK (value IN ('like', 'dislike', 'skip')),
    rated_at timestamptz NOT NULL,
    UNIQUE(rater_id, digest_entry_id)
);

DROP TRIGGER IF EXISTS snapshots_immutable ON snapshots;
CREATE TRIGGER snapshots_immutable BEFORE UPDATE OR DELETE ON snapshots
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

DROP TRIGGER IF EXISTS snapshot_indexes_immutable ON snapshot_indexes;
CREATE TRIGGER snapshot_indexes_immutable BEFORE UPDATE OR DELETE ON snapshot_indexes
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

DROP TRIGGER IF EXISTS sheets_immutable ON sheets;
CREATE TRIGGER sheets_immutable BEFORE UPDATE OR DELETE ON sheets
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

DROP TRIGGER IF EXISTS sheet_questions_immutable ON sheet_questions;
CREATE TRIGGER sheet_questions_immutable BEFORE UPDATE OR DELETE ON sheet_questions
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

DROP TRIGGER IF EXISTS runs_immutable ON runs;
CREATE TRIGGER runs_immutable BEFORE UPDATE OR DELETE ON runs
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

DROP TRIGGER IF EXISTS run_events_immutable ON run_events;
CREATE TRIGGER run_events_immutable BEFORE UPDATE OR DELETE ON run_events
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

DROP TRIGGER IF EXISTS submissions_immutable ON submissions;
CREATE TRIGGER submissions_immutable BEFORE UPDATE OR DELETE ON submissions
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

DROP TRIGGER IF EXISTS submission_evidence_immutable ON submission_evidence;
CREATE TRIGGER submission_evidence_immutable BEFORE UPDATE OR DELETE ON submission_evidence
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

DROP TRIGGER IF EXISTS ratings_immutable ON ratings;
CREATE TRIGGER ratings_immutable BEFORE UPDATE OR DELETE ON ratings
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

INSERT INTO storage_schema_versions(version) VALUES (5) ON CONFLICT DO NOTHING;
