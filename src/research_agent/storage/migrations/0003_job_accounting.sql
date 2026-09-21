ALTER TABLE job_attempts ADD COLUMN IF NOT EXISTS clock_id uuid;
ALTER TABLE job_attempts ADD COLUMN IF NOT EXISTS active_duration_ns bigint NOT NULL DEFAULT 0 CHECK(active_duration_ns>=0);
ALTER TABLE job_attempts ADD COLUMN IF NOT EXISTS duration_complete boolean NOT NULL DEFAULT true;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS result_body bytea;
INSERT INTO storage_schema_versions(version) VALUES(3) ON CONFLICT DO NOTHING;
