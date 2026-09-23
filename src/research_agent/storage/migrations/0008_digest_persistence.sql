CREATE TABLE IF NOT EXISTS digests (
    hash bytea PRIMARY KEY CHECK (octet_length(hash) = 32),
    batch_id bytea NOT NULL CHECK (octet_length(batch_id) = 32),
    island text NOT NULL CHECK (island IN ('cs', 'quant-ph', 'q-bio')),
    source_watermark bigint NOT NULL CHECK (source_watermark >= 0),
    shuffle_seed bytea NOT NULL CHECK (octet_length(shuffle_seed) = 8),
    manifest_hash bytea NOT NULL REFERENCES artifacts(hash) ON DELETE RESTRICT
        CHECK (octet_length(manifest_hash) = 32),
    built_at timestamptz NOT NULL,
    UNIQUE(batch_id, island)
);

CREATE TABLE IF NOT EXISTS digest_entries (
    entry_id uuid PRIMARY KEY,
    digest_hash bytea NOT NULL REFERENCES digests(hash) ON DELETE RESTRICT
        CHECK (octet_length(digest_hash) = 32),
    paper_hash bytea NOT NULL CHECK (octet_length(paper_hash) = 32),
    origin text NOT NULL CHECK (origin IN ('population', 'random_control', 'service')),
    display_position integer NOT NULL CHECK (display_position >= 0),
    service_source text CHECK (service_source IS NULL OR length(service_source) BETWEEN 1 AND 128),
    candidate_pool_hash bytea CHECK (candidate_pool_hash IS NULL OR octet_length(candidate_pool_hash) = 32),
    inclusion_probability double precision
        CHECK (inclusion_probability IS NULL OR inclusion_probability BETWEEN 0 AND 1),
    CHECK ((origin = 'service') = (service_source IS NOT NULL)),
    CHECK ((origin = 'random_control') = (candidate_pool_hash IS NOT NULL)),
    UNIQUE(digest_hash, display_position),
    UNIQUE(digest_hash, paper_hash)
);
CREATE INDEX IF NOT EXISTS digest_entries_digest_hash_idx ON digest_entries(digest_hash);

CREATE TABLE IF NOT EXISTS digest_nominations (
    entry_id uuid NOT NULL REFERENCES digest_entries(entry_id) ON DELETE RESTRICT,
    configuration_id uuid NOT NULL,
    submission_id uuid NOT NULL REFERENCES submissions(id) ON DELETE RESTRICT,
    preference integer NOT NULL CHECK (preference BETWEEN 1 AND 7),
    PRIMARY KEY(entry_id, configuration_id)
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ratings_digest_entry_id_fkey'
    ) THEN
        ALTER TABLE ratings
            ADD CONSTRAINT ratings_digest_entry_id_fkey
            FOREIGN KEY (digest_entry_id) REFERENCES digest_entries(entry_id)
            ON DELETE RESTRICT;
    END IF;
END $$;

DROP TRIGGER IF EXISTS digests_immutable ON digests;
CREATE TRIGGER digests_immutable BEFORE UPDATE OR DELETE ON digests
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

DROP TRIGGER IF EXISTS digest_entries_immutable ON digest_entries;
CREATE TRIGGER digest_entries_immutable BEFORE UPDATE OR DELETE ON digest_entries
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

DROP TRIGGER IF EXISTS digest_nominations_immutable ON digest_nominations;
CREATE TRIGGER digest_nominations_immutable BEFORE UPDATE OR DELETE ON digest_nominations
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

INSERT INTO storage_schema_versions(version) VALUES (8) ON CONFLICT DO NOTHING;
