-- Which job lease produced each artifact published under one. A job may use
-- its own earlier productions as inputs, so a checkpoint can name its outputs.
CREATE TABLE IF NOT EXISTS job_productions (
    manifest_hash bytea PRIMARY KEY REFERENCES artifact_productions(manifest_hash)
        ON DELETE RESTRICT,
    job_id uuid NOT NULL REFERENCES jobs(id) ON DELETE RESTRICT,
    lease_epoch bigint NOT NULL CHECK (lease_epoch > 0)
);
CREATE INDEX IF NOT EXISTS job_productions_job_idx ON job_productions(job_id);

DROP TRIGGER IF EXISTS job_productions_immutable ON job_productions;
CREATE TRIGGER job_productions_immutable
BEFORE UPDATE OR DELETE ON job_productions
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

INSERT INTO storage_schema_versions(version) VALUES (4) ON CONFLICT DO NOTHING;
