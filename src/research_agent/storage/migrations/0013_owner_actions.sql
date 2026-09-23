CREATE TABLE IF NOT EXISTS owner_principals (
    owner_id uuid PRIMARY KEY,
    salt bytea NOT NULL CHECK (octet_length(salt) = 16),
    credential_hash bytea NOT NULL CHECK (octet_length(credential_hash) = 32),
    provisioned_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

DROP TRIGGER IF EXISTS owner_principals_immutable ON owner_principals;
CREATE TRIGGER owner_principals_immutable BEFORE UPDATE OR DELETE ON owner_principals
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

-- Records that an owner, not FT-14's automatic selection or the initial
-- seed activation, requested one genome's admission: an edit-and-admit
-- names the source genome it was prefilled from (AG-16, AG-20, SR-19); a
-- seed-a-variant names none. The admitted genome itself is the ordinary
-- immutable genomes row this table only names the requester of (#139).
CREATE TABLE IF NOT EXISTS genome_owner_admissions (
    configuration_id uuid PRIMARY KEY
        REFERENCES genomes(configuration_id) ON DELETE RESTRICT,
    owner_id uuid NOT NULL REFERENCES owner_principals(owner_id) ON DELETE RESTRICT,
    kind text NOT NULL CHECK (kind IN ('edit', 'seed')),
    source_configuration_id uuid REFERENCES genomes(configuration_id) ON DELETE RESTRICT,
    requested_at timestamptz NOT NULL,
    CHECK ((kind = 'edit') = (source_configuration_id IS NOT NULL))
);

DROP TRIGGER IF EXISTS genome_owner_admissions_immutable ON genome_owner_admissions;
CREATE TRIGGER genome_owner_admissions_immutable BEFORE UPDATE OR DELETE ON genome_owner_admissions
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

-- An owner's request to remove one genome from the active population at
-- the next selection cycle (#139). Its runs, claims and scores are named
-- nowhere here and stay exactly as sealed; the diversity archive keeps the
-- genome under FT-15's existing rule whenever a select stage later retires
-- its lineage. One request per genome; a founder is never retired (AG-38).
CREATE TABLE IF NOT EXISTS genome_retirements (
    configuration_id uuid PRIMARY KEY
        REFERENCES genomes(configuration_id) ON DELETE RESTRICT,
    owner_id uuid NOT NULL REFERENCES owner_principals(owner_id) ON DELETE RESTRICT,
    requested_at timestamptz NOT NULL
);

DROP TRIGGER IF EXISTS genome_retirements_immutable ON genome_retirements;
CREATE TRIGGER genome_retirements_immutable BEFORE UPDATE OR DELETE ON genome_retirements
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
    'score_published', 'run_budget_reserved', 'run_budget_reconciled', 'resolution_recorded',
    'operational_finding_recorded', 'genome_admitted', 'genome_archived',
    'owner_provisioned', 'genome_owner_admission_recorded', 'genome_retirement_requested'
));

INSERT INTO storage_schema_versions(version) VALUES (13) ON CONFLICT DO NOTHING;
