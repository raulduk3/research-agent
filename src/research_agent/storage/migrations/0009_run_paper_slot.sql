DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_attribute
        WHERE attrelid = 'runs'::regclass
          AND attname = 'shard_id'
          AND NOT attisdropped
    ) THEN
        ALTER TABLE runs RENAME COLUMN shard_id TO paper_id;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'runs'::regclass
          AND conname = 'runs_batch_id_shard_id_configuration_id_attempt_key'
    ) THEN
        ALTER TABLE runs RENAME CONSTRAINT runs_batch_id_shard_id_configuration_id_attempt_key
            TO runs_batch_id_paper_id_configuration_id_attempt_key;
    END IF;
END $$;

ALTER TABLE runs ADD COLUMN IF NOT EXISTS issued_question_ids uuid[] NOT NULL DEFAULT '{}';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'runs'::regclass
          AND conname = 'runs_issued_question_ids_check'
    ) THEN
        ALTER TABLE runs ADD CONSTRAINT runs_issued_question_ids_check CHECK (
            array_length(issued_question_ids, 1) IS NULL
            OR array_length(issued_question_ids, 1) BETWEEN 1 AND 3
        );
    END IF;
END $$;

-- AG-26 (TDD-3.1.57): one accepted submit per run, its per-question forecast
-- answers and its one nomination for the run's own paper. Uniqueness of the
-- accepted submission is the table's own primary key, not a run state
-- column: full run lifecycle state (TDD-2.1.44, TDD-3.1.55) is #73's own
-- later addition.
CREATE TABLE IF NOT EXISTS run_submissions (
    run_id uuid PRIMARY KEY REFERENCES runs(id) ON DELETE RESTRICT,
    submission_id uuid NOT NULL,
    request_hash bytea NOT NULL CHECK (octet_length(request_hash) = 32),
    accepted_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS run_forecasts (
    run_id uuid NOT NULL REFERENCES run_submissions(run_id) ON DELETE RESTRICT,
    question_id uuid NOT NULL,
    probability double precision NOT NULL CHECK (probability BETWEEN 0 AND 1),
    rationale text NOT NULL CHECK (length(rationale) BETWEEN 1 AND 2000),
    PRIMARY KEY(run_id, question_id)
);

CREATE TABLE IF NOT EXISTS run_forecast_evidence (
    run_id uuid NOT NULL,
    question_id uuid NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal >= 0 AND ordinal < 5),
    evidence_hash bytea NOT NULL CHECK (octet_length(evidence_hash) = 32),
    PRIMARY KEY(run_id, question_id, ordinal),
    FOREIGN KEY(run_id, question_id) REFERENCES run_forecasts(run_id, question_id)
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS run_nominations (
    run_id uuid PRIMARY KEY REFERENCES run_submissions(run_id) ON DELETE RESTRICT,
    paper_id text NOT NULL CHECK (length(paper_id) BETWEEN 1 AND 128),
    recommend boolean NOT NULL,
    preference double precision NOT NULL CHECK (preference BETWEEN 0 AND 1),
    rationale text NOT NULL CHECK (length(rationale) BETWEEN 1 AND 2000)
);

DROP TRIGGER IF EXISTS run_submissions_immutable ON run_submissions;
CREATE TRIGGER run_submissions_immutable BEFORE UPDATE OR DELETE ON run_submissions
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

DROP TRIGGER IF EXISTS run_forecasts_immutable ON run_forecasts;
CREATE TRIGGER run_forecasts_immutable BEFORE UPDATE OR DELETE ON run_forecasts
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

DROP TRIGGER IF EXISTS run_forecast_evidence_immutable ON run_forecast_evidence;
CREATE TRIGGER run_forecast_evidence_immutable BEFORE UPDATE OR DELETE ON run_forecast_evidence
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

DROP TRIGGER IF EXISTS run_nominations_immutable ON run_nominations;
CREATE TRIGGER run_nominations_immutable BEFORE UPDATE OR DELETE ON run_nominations
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

INSERT INTO storage_schema_versions(version) VALUES (9) ON CONFLICT DO NOTHING;
