-- #298: each embedded paper version's embedding view is a stored artifact;
-- this table points a family at the views built for its versions. A row is
-- immutable: a rebuild that measures something new appends a row, and the
-- family's current view is its most recently recorded one.
CREATE TABLE IF NOT EXISTS embedding_views (
    paper_family_id uuid NOT NULL,
    paper_version_id uuid NOT NULL,
    view_hash bytea NOT NULL REFERENCES artifacts(hash) ON DELETE RESTRICT
        CHECK (octet_length(view_hash) = 32),
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY(paper_version_id, view_hash)
);
CREATE INDEX IF NOT EXISTS embedding_views_family_idx
    ON embedding_views(paper_family_id, recorded_at DESC, view_hash DESC);

DROP TRIGGER IF EXISTS embedding_views_immutable ON embedding_views;
CREATE TRIGGER embedding_views_immutable BEFORE UPDATE OR DELETE ON embedding_views
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

INSERT INTO storage_schema_versions(version) VALUES (22) ON CONFLICT DO NOTHING;
