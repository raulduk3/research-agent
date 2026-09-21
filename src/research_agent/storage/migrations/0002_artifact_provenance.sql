INSERT INTO storage_schema_versions(version) VALUES (2)
ON CONFLICT (version) DO NOTHING;

CREATE TABLE IF NOT EXISTS artifact_productions (
    manifest_hash bytea PRIMARY KEY REFERENCES artifacts(hash) ON DELETE RESTRICT
        CHECK (octet_length(manifest_hash) = 32),
    artifact_hash bytea NOT NULL REFERENCES artifacts(hash) ON DELETE RESTRICT
        CHECK (octet_length(artifact_hash) = 32),
    created_at timestamptz NOT NULL,
    producer_image_digest bytea NOT NULL CHECK (octet_length(producer_image_digest) = 32),
    producer_source_commit bytea NOT NULL CHECK (octet_length(producer_source_commit) = 20),
    producer_contract_version integer NOT NULL CHECK (producer_contract_version = 1),
    config_hash bytea NOT NULL CHECK (octet_length(config_hash) = 32),
    retention_policy_hash bytea NOT NULL CHECK (octet_length(retention_policy_hash) = 32)
);
CREATE INDEX IF NOT EXISTS artifact_productions_artifact_hash_idx
ON artifact_productions(artifact_hash);

CREATE TABLE IF NOT EXISTS artifact_production_edges (
    manifest_hash bytea NOT NULL REFERENCES artifact_productions(manifest_hash)
        ON DELETE RESTRICT,
    input_hash bytea NOT NULL REFERENCES artifacts(hash) ON DELETE RESTRICT,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY(manifest_hash, ordinal),
    UNIQUE(manifest_hash, input_hash)
);
CREATE INDEX IF NOT EXISTS artifact_production_edges_input_hash_idx
ON artifact_production_edges(input_hash);

DROP TRIGGER IF EXISTS artifact_productions_immutable ON artifact_productions;
CREATE TRIGGER artifact_productions_immutable
BEFORE UPDATE OR DELETE ON artifact_productions
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

DROP TRIGGER IF EXISTS artifact_production_edges_immutable ON artifact_production_edges;
CREATE TRIGGER artifact_production_edges_immutable
BEFORE UPDATE OR DELETE ON artifact_production_edges
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();
