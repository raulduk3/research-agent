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
    'operational_finding_recorded', 'genome_admitted', 'genome_archived'
));

-- AG-16, AG-20, AG-21, FT-15: the seeded population. A genome row is its
-- admission record: seeded (no parent) or an accepted child (AG-21), under
-- the profile that admitted it. `configuration_id` is the same identity
-- `runs.configuration_id` carries, so a genome that has never run is still
-- enumerable. Rows never change; an archived genome stays here and gains a
-- `genome_archive` row, so the unique configuration hash bounds AG-21
-- against active and archived genomes alike.
CREATE TABLE IF NOT EXISTS genomes (
    configuration_id uuid PRIMARY KEY,
    configuration_hash bytea NOT NULL UNIQUE CHECK (octet_length(configuration_hash) = 32),
    lineage_id text NOT NULL CHECK (length(lineage_id) BETWEEN 1 AND 128),
    island text NOT NULL CHECK (island IN ('cs', 'quant-ph', 'q-bio')),
    founder boolean NOT NULL,
    infra_hash bytea NOT NULL CHECK (octet_length(infra_hash) = 32),
    parent_hash bytea REFERENCES genomes(configuration_hash) ON DELETE RESTRICT
        CHECK (parent_hash IS NULL OR octet_length(parent_hash) = 32),
    admission text NOT NULL CHECK (admission IN ('seeded', 'accepted')),
    profile_hash bytea NOT NULL CHECK (octet_length(profile_hash) = 32),
    admitted_at timestamptz NOT NULL,
    CHECK ((admission = 'seeded') = (parent_hash IS NULL))
);
CREATE INDEX IF NOT EXISTS genomes_admitted_at_idx ON genomes(admitted_at, configuration_id);
CREATE INDEX IF NOT EXISTS genomes_island_idx ON genomes(island);

-- AG-20: the four emphasis parts, each hashed on its own.
CREATE TABLE IF NOT EXISTS genome_parts (
    configuration_id uuid NOT NULL REFERENCES genomes(configuration_id) ON DELETE RESTRICT,
    part text NOT NULL CHECK (
        part IN ('prompt', 'scan_policy', 'read_policy', 'probability_assignment_rule')
    ),
    value text NOT NULL CHECK (length(value) >= 1),
    value_hash bytea NOT NULL CHECK (octet_length(value_hash) = 32),
    PRIMARY KEY(configuration_id, part)
);

-- FT-15: a retired lineage's best member, with the skill and support it
-- was archived on. An archived genome runs no further.
CREATE TABLE IF NOT EXISTS genome_archive (
    configuration_id uuid PRIMARY KEY REFERENCES genomes(configuration_id) ON DELETE RESTRICT,
    cycle_id text NOT NULL CHECK (length(cycle_id) BETWEEN 1 AND 128),
    skill double precision NOT NULL,
    resolved_claim_count integer NOT NULL CHECK (resolved_claim_count >= 0),
    profile_hash bytea NOT NULL CHECK (octet_length(profile_hash) = 32),
    archived_at timestamptz NOT NULL
);

DROP TRIGGER IF EXISTS genomes_immutable ON genomes;
CREATE TRIGGER genomes_immutable BEFORE UPDATE OR DELETE ON genomes
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

DROP TRIGGER IF EXISTS genome_parts_immutable ON genome_parts;
CREATE TRIGGER genome_parts_immutable BEFORE UPDATE OR DELETE ON genome_parts
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

DROP TRIGGER IF EXISTS genome_archive_immutable ON genome_archive;
CREATE TRIGGER genome_archive_immutable BEFORE UPDATE OR DELETE ON genome_archive
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

INSERT INTO storage_schema_versions(version) VALUES (12) ON CONFLICT DO NOTHING;
