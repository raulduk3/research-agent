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
    'rating_recorded', 'human_forecast_sealed', 'alert_acknowledged', 'spend_reserved',
    'spend_reconciled', 'study_imported', 'anchor_received', 'score_published',
    'run_budget_reserved', 'run_budget_reconciled'
));

CREATE TABLE IF NOT EXISTS snapshot_items (
    snapshot_hash bytea NOT NULL REFERENCES snapshots(hash) ON DELETE RESTRICT
        CHECK (octet_length(snapshot_hash) = 32),
    paper_family_id uuid NOT NULL,
    paper_version_id uuid NOT NULL,
    card_hash bytea NOT NULL REFERENCES artifacts(hash) ON DELETE RESTRICT
        CHECK (octet_length(card_hash) = 32),
    overview_hash bytea REFERENCES artifacts(hash) ON DELETE RESTRICT
        CHECK (overview_hash IS NULL OR octet_length(overview_hash) = 32),
    passage_index_hash bytea REFERENCES artifacts(hash) ON DELETE RESTRICT
        CHECK (passage_index_hash IS NULL OR octet_length(passage_index_hash) = 32),
    graph_hash bytea REFERENCES artifacts(hash) ON DELETE RESTRICT
        CHECK (graph_hash IS NULL OR octet_length(graph_hash) = 32),
    PRIMARY KEY(snapshot_hash, paper_version_id)
);
CREATE INDEX IF NOT EXISTS snapshot_items_family_idx
    ON snapshot_items(snapshot_hash, paper_family_id);

CREATE TABLE IF NOT EXISTS snapshot_sheets (
    snapshot_hash bytea NOT NULL REFERENCES snapshots(hash) ON DELETE RESTRICT
        CHECK (octet_length(snapshot_hash) = 32),
    sheet_hash bytea NOT NULL REFERENCES sheets(hash) ON DELETE RESTRICT
        CHECK (octet_length(sheet_hash) = 32),
    PRIMARY KEY(snapshot_hash, sheet_hash)
);

DROP TRIGGER IF EXISTS snapshot_items_immutable ON snapshot_items;
CREATE TRIGGER snapshot_items_immutable BEFORE UPDATE OR DELETE ON snapshot_items
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

DROP TRIGGER IF EXISTS snapshot_sheets_immutable ON snapshot_sheets;
CREATE TRIGGER snapshot_sheets_immutable BEFORE UPDATE OR DELETE ON snapshot_sheets
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

INSERT INTO storage_schema_versions(version) VALUES (6) ON CONFLICT DO NOTHING;
