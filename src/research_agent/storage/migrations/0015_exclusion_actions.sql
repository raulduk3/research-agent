-- AG-22, AG-23, TDD-3.1.69, TDD-3.1.70: graduated exclusion actions. One
-- immutable row per step applied, each naming the ledger record appended in
-- the same transaction. The state of a run or configuration is its latest
-- row, so an exclusion held only in working state cannot exist. A scope
-- reaches each state at most once, which is what refuses a repeated step; the
-- storage code refuses a skipped one. Nothing here deletes an audit record:
-- authority_revoked is a state, not a removal.
CREATE TABLE IF NOT EXISTS exclusion_transitions (
    id uuid PRIMARY KEY,
    action text NOT NULL CHECK (
        action IN ('quarantine_run', 'quarantine_configuration', 'revoke_authority')
    ),
    scope text NOT NULL CHECK (scope IN ('run', 'configuration')),
    scope_id uuid NOT NULL,
    configuration_id uuid NOT NULL,
    prior_state text NOT NULL CHECK (
        prior_state IN ('active', 'run_quarantined', 'configuration_quarantined')
    ),
    new_state text NOT NULL CHECK (
        new_state IN ('run_quarantined', 'configuration_quarantined', 'authority_revoked')
    ),
    run_id uuid REFERENCES runs(id) ON DELETE RESTRICT,
    trigger_run_ids uuid[] NOT NULL,
    evidence_hashes bytea[] NOT NULL CHECK (cardinality(evidence_hashes) >= 1),
    authority text NOT NULL CHECK (authority IN ('system', 'operator')),
    operator_id uuid REFERENCES owner_principals(owner_id) ON DELETE RESTRICT,
    ledger_sequence bigint NOT NULL UNIQUE
        REFERENCES ledger_records(sequence) ON DELETE RESTRICT,
    recorded_at timestamptz NOT NULL,
    UNIQUE(scope, scope_id, new_state),
    CHECK ((authority = 'operator') = (operator_id IS NOT NULL)),
    CHECK ((scope = 'run') = (run_id IS NOT NULL)),
    CHECK (run_id IS NULL OR run_id = scope_id),
    CHECK (scope = 'run' OR scope_id = configuration_id),
    CHECK (
        (action = 'quarantine_run'
            AND scope = 'run' AND prior_state = 'active'
            AND new_state = 'run_quarantined')
        OR (action = 'quarantine_configuration'
            AND scope = 'configuration' AND prior_state = 'active'
            AND new_state = 'configuration_quarantined')
        OR (action = 'revoke_authority'
            AND scope = 'configuration' AND prior_state = 'configuration_quarantined'
            AND new_state = 'authority_revoked' AND authority = 'operator')
    )
);
CREATE INDEX IF NOT EXISTS exclusion_transitions_configuration_idx
    ON exclusion_transitions(configuration_id, recorded_at);

DROP TRIGGER IF EXISTS exclusion_transitions_immutable ON exclusion_transitions;
CREATE TRIGGER exclusion_transitions_immutable BEFORE UPDATE OR DELETE ON exclusion_transitions
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
    'preference_credit_recorded', 'preference_credit_gap_recorded',
    'exclusion_action_recorded'
));

INSERT INTO storage_schema_versions(version) VALUES (15) ON CONFLICT DO NOTHING;
