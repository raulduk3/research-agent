-- IN-43, TDD-4.1.79: a rating's credit to each genome whose sealed submission
-- nominated the rated paper. A credit row is immutable and cites the rating,
-- the digest entry and the genome it credits; nothing here is readable by the
-- scorer's projection or the resolver. A rating whose nominating submissions
-- could not be read carries a gap row instead of any credit.
CREATE TABLE IF NOT EXISTS preference_credits (
    rating_id uuid NOT NULL REFERENCES ratings(id) ON DELETE RESTRICT,
    genome_hash bytea NOT NULL REFERENCES genomes(configuration_hash) ON DELETE RESTRICT
        CHECK (octet_length(genome_hash) = 32),
    island text NOT NULL CHECK (island IN ('cs', 'quant-ph', 'q-bio')),
    entry_id uuid NOT NULL REFERENCES digest_entries(entry_id) ON DELETE RESTRICT,
    sealed_probability double precision NOT NULL
        CHECK (sealed_probability BETWEEN 0 AND 1),
    share double precision NOT NULL CHECK (share BETWEEN -1 AND 1 AND share <> 0),
    iso_week text NOT NULL CHECK (iso_week ~ '^[0-9]{4}-W(0[1-9]|[1-4][0-9]|5[0-3])$'),
    PRIMARY KEY(rating_id, genome_hash)
);
CREATE INDEX IF NOT EXISTS preference_credits_week_idx
    ON preference_credits(island, iso_week);

CREATE TABLE IF NOT EXISTS preference_credit_gaps (
    rating_id uuid PRIMARY KEY REFERENCES ratings(id) ON DELETE RESTRICT,
    iso_week text NOT NULL CHECK (iso_week ~ '^[0-9]{4}-W(0[1-9]|[1-4][0-9]|5[0-3])$'),
    reason text NOT NULL CHECK (length(reason) BETWEEN 1 AND 512),
    recorded_at timestamptz NOT NULL
);

DROP TRIGGER IF EXISTS preference_credits_immutable ON preference_credits;
CREATE TRIGGER preference_credits_immutable BEFORE UPDATE OR DELETE ON preference_credits
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

DROP TRIGGER IF EXISTS preference_credit_gaps_immutable ON preference_credit_gaps;
CREATE TRIGGER preference_credit_gaps_immutable BEFORE UPDATE OR DELETE ON preference_credit_gaps
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
    'owner_provisioned', 'genome_owner_admission_recorded', 'genome_retirement_requested',
    'preference_credit_recorded', 'preference_credit_gap_recorded'
));

INSERT INTO storage_schema_versions(version) VALUES (14) ON CONFLICT DO NOTHING;
