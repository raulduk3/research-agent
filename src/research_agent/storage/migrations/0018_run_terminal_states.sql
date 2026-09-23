-- AG-15 (TDD-3.1.55): a run ends exactly once, either with its accepted
-- submission or void. The terminal row's primary key is the compare-and-set:
-- accept_submission and finish_without_submit both insert it, so a racing
-- pair cannot both win, and `runs` itself stays immutable. A void row carries
-- the reason, the last recorded run event and the run's complete stamp
-- (SR-15) copied from its run specification.
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
    'exclusion_action_recorded', 'paper_requested', 'run_voided'
));

CREATE TABLE IF NOT EXISTS run_terminal_states (
    run_id uuid PRIMARY KEY REFERENCES runs(id) ON DELETE RESTRICT,
    state text NOT NULL CHECK (state IN ('submitted', 'void')),
    reason text CHECK (reason IS NULL OR length(reason) BETWEEN 1 AND 128),
    last_event_attempt integer CHECK (last_event_attempt IS NULL OR last_event_attempt > 0),
    last_event_ordinal integer CHECK (last_event_ordinal IS NULL OR last_event_ordinal >= 0),
    stamp bytea,
    ended_at timestamptz NOT NULL,
    CHECK ((state = 'void') = (reason IS NOT NULL AND stamp IS NOT NULL)),
    CHECK ((last_event_attempt IS NULL) = (last_event_ordinal IS NULL)),
    CHECK (state = 'void' OR last_event_attempt IS NULL)
);

DROP TRIGGER IF EXISTS run_terminal_states_immutable ON run_terminal_states;
CREATE TRIGGER run_terminal_states_immutable BEFORE UPDATE OR DELETE ON run_terminal_states
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

INSERT INTO run_terminal_states(run_id, state, ended_at)
SELECT run_id, 'submitted', accepted_at FROM run_submissions
ON CONFLICT (run_id) DO NOTHING;

INSERT INTO storage_schema_versions(version) VALUES (18) ON CONFLICT DO NOTHING;
