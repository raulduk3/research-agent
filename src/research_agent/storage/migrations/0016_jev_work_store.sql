-- RD-19 to RD-21, TDD-4.1.58, TDD-4.1.59: the Jev work store and the card
-- section's assessment pointers.
--
-- A lease is a row with an expiry, so a crashed worker's key frees itself and
-- a release only moves the expiry to now; no table here is ever deleted from.
-- The UTC day's attempt and reserved-spend totals live in one row per day, so
-- checking a cap and counting the attempt is one atomic update whichever
-- connection asks. A reservation is settled once and keeps its worst-case
-- cost in the day's total. Attempt manifests are append-only: the key's
-- committed attempt is its latest row, and committed_at is the time the
-- result became available to a snapshot. The current pointer for a paper
-- version moves only by compare-and-swap; a snapshot's pin is written once
-- and never moves.
CREATE TABLE IF NOT EXISTS jev_work_leases (
    work_key bytea PRIMARY KEY CHECK (octet_length(work_key) = 32),
    holder uuid NOT NULL,
    expires_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS jev_daily_usage (
    day date PRIMARY KEY,
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    reserved_micros bigint NOT NULL DEFAULT 0 CHECK (reserved_micros >= 0)
);

CREATE TABLE IF NOT EXISTS jev_attempt_reservations (
    id uuid PRIMARY KEY,
    work_key bytea NOT NULL CHECK (octet_length(work_key) = 32),
    day date NOT NULL,
    worst_case_micros bigint NOT NULL CHECK (worst_case_micros >= 0),
    billing_state text CHECK (
        billing_state IS NULL OR billing_state IN (
            'no_attempt', 'known_rejected', 'known_completed', 'uncertain'
        )
    ),
    reserved_at timestamptz NOT NULL,
    settled_at timestamptz,
    CHECK ((billing_state IS NULL) = (settled_at IS NULL))
);
CREATE INDEX IF NOT EXISTS jev_attempt_reservations_work_key_idx
    ON jev_attempt_reservations(work_key);

CREATE TABLE IF NOT EXISTS jev_attempt_manifests (
    id bigserial PRIMARY KEY,
    work_key bytea NOT NULL CHECK (octet_length(work_key) = 32),
    manifest_hash bytea NOT NULL CHECK (octet_length(manifest_hash) = 32),
    manifest bytea NOT NULL CHECK (octet_length(manifest) BETWEEN 1 AND 1048576),
    committed_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS jev_attempt_manifests_work_key_idx
    ON jev_attempt_manifests(work_key, id);

CREATE TABLE IF NOT EXISTS assessment_pointers (
    paper_version_id uuid PRIMARY KEY,
    section_hash bytea NOT NULL CHECK (octet_length(section_hash) = 32),
    updated_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS assessment_snapshot_pins (
    snapshot_hash bytea NOT NULL,
    paper_version_id uuid NOT NULL,
    section_hash bytea NOT NULL CHECK (octet_length(section_hash) = 32),
    pinned_at timestamptz NOT NULL,
    PRIMARY KEY(snapshot_hash, paper_version_id),
    FOREIGN KEY(snapshot_hash, paper_version_id)
        REFERENCES snapshot_items(snapshot_hash, paper_version_id) ON DELETE RESTRICT
);

DROP TRIGGER IF EXISTS jev_attempt_manifests_immutable ON jev_attempt_manifests;
CREATE TRIGGER jev_attempt_manifests_immutable
BEFORE UPDATE OR DELETE ON jev_attempt_manifests
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

DROP TRIGGER IF EXISTS assessment_snapshot_pins_immutable ON assessment_snapshot_pins;
CREATE TRIGGER assessment_snapshot_pins_immutable
BEFORE UPDATE OR DELETE ON assessment_snapshot_pins
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

INSERT INTO storage_schema_versions(version) VALUES (16) ON CONFLICT DO NOTHING;
