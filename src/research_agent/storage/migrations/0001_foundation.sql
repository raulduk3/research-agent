CREATE TABLE IF NOT EXISTS storage_schema_versions (
    version integer PRIMARY KEY CHECK (version > 0),
    installed_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);

INSERT INTO storage_schema_versions(version) VALUES (1)
ON CONFLICT (version) DO NOTHING;

CREATE TABLE IF NOT EXISTS artifacts (
    hash bytea PRIMARY KEY CHECK (octet_length(hash) = 32),
    byte_length bigint NOT NULL CHECK (byte_length >= 0),
    media_type text NOT NULL CHECK (media_type IN (
        'application/json', 'application/pdf', 'application/octet-stream',
        'image/png', 'text/plain'
    )),
    kind text NOT NULL CHECK (kind IN (
        'source_response', 'source_document', 'extraction', 'vector_payload',
        'model_weights', 'tokenizer', 'manifest', 'tool_request',
        'tool_response', 'provider_response', 'study_evidence', 'signature_evidence'
    )),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    available_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    retention_policy_hash bytea NOT NULL CHECK (octet_length(retention_policy_hash) = 32),
    producer_image_digest bytea NOT NULL CHECK (octet_length(producer_image_digest) = 32),
    producer_source_commit bytea NOT NULL CHECK (octet_length(producer_source_commit) = 20),
    producer_contract_version integer NOT NULL CHECK (producer_contract_version = 1),
    config_hash bytea NOT NULL CHECK (octet_length(config_hash) = 32)
);

CREATE TABLE IF NOT EXISTS artifact_edges (
    output_hash bytea NOT NULL REFERENCES artifacts(hash) ON DELETE RESTRICT,
    input_hash bytea NOT NULL REFERENCES artifacts(hash) ON DELETE RESTRICT,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY(output_hash, ordinal),
    UNIQUE(output_hash, input_hash),
    CHECK(output_hash <> input_hash)
);
CREATE INDEX IF NOT EXISTS artifact_edges_input_hash_idx ON artifact_edges(input_hash);

CREATE TABLE IF NOT EXISTS artifact_tombstones (
    id uuid PRIMARY KEY,
    artifact_hash bytea NOT NULL UNIQUE REFERENCES artifacts(hash) ON DELETE RESTRICT,
    reason text NOT NULL CHECK (length(reason) > 0),
    policy_hash bytea NOT NULL CHECK (octet_length(policy_hash) = 32),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);

CREATE TABLE IF NOT EXISTS idempotency_records (
    principal_id uuid NOT NULL,
    key uuid NOT NULL,
    command_id uuid NOT NULL,
    content_hash bytea NOT NULL CHECK (octet_length(content_hash) = 32),
    status_code integer CHECK (status_code BETWEEN 200 AND 599),
    response_body bytea,
    completed boolean NOT NULL DEFAULT false,
    committed_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    PRIMARY KEY(principal_id, key),
    UNIQUE(principal_id, command_id)
);

CREATE TABLE IF NOT EXISTS ledger_records (
    sequence bigint PRIMARY KEY CHECK (sequence > 0),
    record_id uuid NOT NULL UNIQUE,
    previous_record_hash bytea NOT NULL CHECK (octet_length(previous_record_hash) = 32),
    record_hash bytea NOT NULL UNIQUE CHECK (octet_length(record_hash) = 32),
    event_kind text NOT NULL CHECK (event_kind IN (
        'artifact_committed', 'paper_observed', 'job_transition', 'snapshot_sealed',
        'run_created', 'run_event', 'submission_accepted', 'bundle_activated',
        'digest_created', 'rating_recorded', 'human_forecast_sealed',
        'alert_acknowledged', 'spend_reserved', 'spend_reconciled', 'study_imported',
        'anchor_received', 'score_published', 'run_budget_reserved',
        'run_budget_reconciled'
    )),
    payload_hash bytea NOT NULL REFERENCES artifacts(hash) ON DELETE RESTRICT
        CHECK (octet_length(payload_hash) = 32),
    created_at timestamptz NOT NULL,
    command_id uuid NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger_head (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    sequence bigint NOT NULL CHECK (sequence >= 0),
    record_hash bytea NOT NULL CHECK (octet_length(record_hash) = 32)
);
INSERT INTO ledger_head(singleton, sequence, record_hash)
VALUES (true, 0, decode(repeat('00', 32), 'hex'))
ON CONFLICT (singleton) DO NOTHING;

CREATE TABLE IF NOT EXISTS artifact_publication_receipts (
    artifact_hash bytea PRIMARY KEY REFERENCES artifacts(hash) ON DELETE RESTRICT,
    committed_ledger_sequence bigint NOT NULL REFERENCES ledger_records(sequence)
        ON DELETE RESTRICT CHECK (committed_ledger_sequence > 0),
    published_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id uuid PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN (
        'capture', 'extract', 'embed', 'label', 'fit', 'calibrate',
        'predict', 'assess', 'qualify', 'baseline', 'score', 'audit'
    )),
    state text NOT NULL CHECK (state IN (
        'queued', 'running', 'interrupted', 'committed', 'failed', 'skipped'
    )),
    input_manifest_hash bytea NOT NULL REFERENCES artifacts(hash) ON DELETE RESTRICT,
    scheduled_at timestamptz NOT NULL,
    lease_epoch bigint NOT NULL DEFAULT 0 CHECK (lease_epoch >= 0),
    worker_id uuid,
    expires_at timestamptz,
    checkpoint_hash bytea REFERENCES artifacts(hash) ON DELETE RESTRICT,
    first_started_at timestamptz,
    terminal_at timestamptz,
    accumulated_active_duration_ns bigint NOT NULL DEFAULT 0 CHECK (accumulated_active_duration_ns >= 0),
    CHECK ((worker_id IS NULL) = (expires_at IS NULL)),
    CHECK ((state = 'running') = (worker_id IS NOT NULL)),
    CHECK ((state IN ('committed', 'failed', 'skipped')) = (terminal_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS jobs_claim_idx ON jobs(state, scheduled_at, id);

CREATE TABLE IF NOT EXISTS job_attempts (
    id uuid PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES jobs(id) ON DELETE RESTRICT,
    lease_epoch bigint NOT NULL CHECK (lease_epoch > 0),
    worker_id uuid NOT NULL,
    started_at timestamptz NOT NULL,
    ended_at timestamptz,
    status text NOT NULL CHECK (status IN ('running', 'expired', 'committed', 'failed', 'skipped')),
    UNIQUE(job_id, lease_epoch),
    CHECK ((status = 'running') = (ended_at IS NULL))
);

CREATE TABLE IF NOT EXISTS job_checkpoints (
    id uuid PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES jobs(id) ON DELETE RESTRICT,
    lease_epoch bigint NOT NULL CHECK (lease_epoch > 0),
    artifact_hash bytea NOT NULL REFERENCES artifacts(hash) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    FOREIGN KEY(job_id, lease_epoch) REFERENCES job_attempts(job_id, lease_epoch)
);
CREATE INDEX IF NOT EXISTS job_checkpoints_lookup_idx
ON job_checkpoints(job_id, lease_epoch, created_at);

CREATE TABLE IF NOT EXISTS job_outputs (
    job_id uuid NOT NULL REFERENCES jobs(id) ON DELETE RESTRICT,
    artifact_hash bytea NOT NULL REFERENCES artifacts(hash) ON DELETE RESTRICT,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY(job_id, ordinal),
    UNIQUE(job_id, artifact_hash)
);

CREATE OR REPLACE FUNCTION reject_immutable_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'immutable relation % cannot be changed', TG_TABLE_NAME
        USING ERRCODE = '55000';
END;
$$;

DROP TRIGGER IF EXISTS ledger_records_immutable ON ledger_records;
CREATE TRIGGER ledger_records_immutable BEFORE UPDATE OR DELETE ON ledger_records
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

DROP TRIGGER IF EXISTS artifacts_immutable ON artifacts;
CREATE TRIGGER artifacts_immutable BEFORE UPDATE OR DELETE ON artifacts
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

DROP TRIGGER IF EXISTS artifact_edges_immutable ON artifact_edges;
CREATE TRIGGER artifact_edges_immutable BEFORE UPDATE OR DELETE ON artifact_edges
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

DROP TRIGGER IF EXISTS artifact_tombstones_immutable ON artifact_tombstones;
CREATE TRIGGER artifact_tombstones_immutable BEFORE UPDATE OR DELETE ON artifact_tombstones
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

DROP TRIGGER IF EXISTS artifact_publication_receipts_immutable ON artifact_publication_receipts;
CREATE TRIGGER artifact_publication_receipts_immutable
BEFORE UPDATE OR DELETE ON artifact_publication_receipts
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

CREATE OR REPLACE FUNCTION protect_completed_idempotency() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.completed THEN
        RAISE EXCEPTION 'completed idempotency record cannot be changed'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS idempotency_completed_immutable ON idempotency_records;
CREATE TRIGGER idempotency_completed_immutable BEFORE UPDATE OR DELETE ON idempotency_records
FOR EACH ROW EXECUTE FUNCTION protect_completed_idempotency();

CREATE OR REPLACE FUNCTION require_completed_idempotency() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    is_completed boolean;
BEGIN
    SELECT completed INTO is_completed
    FROM idempotency_records
    WHERE principal_id = NEW.principal_id AND key = NEW.key;
    IF is_completed IS DISTINCT FROM true THEN
        RAISE EXCEPTION 'idempotency claim must be completed before commit'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS idempotency_must_complete ON idempotency_records;
CREATE CONSTRAINT TRIGGER idempotency_must_complete
AFTER INSERT OR UPDATE ON idempotency_records
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION require_completed_idempotency();
