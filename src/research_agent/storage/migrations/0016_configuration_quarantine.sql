-- IN-24, TDD-4.1.31: a run whose recomputed configuration digest differs from
-- the one sealed at start is quarantined through the exclusion path. A
-- quarantined run's submission cannot be nominated into a digest: the refusal
-- is in the schema, so no writer can skip it. Rating a quarantined output is
-- refused by the rating repository.
-- Created only when absent: roles.py adopts an already migrated schema by
-- transferring its listed objects, and this function is not among them, so a
-- second run by the migrator must not try to replace it.
DO $migration$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgrelid = 'digest_nominations'::regclass
          AND tgname = 'digest_nominations_quarantine'
    ) THEN
        RETURN;
    END IF;
    CREATE FUNCTION reject_quarantined_nomination() RETURNS trigger AS $$
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM run_submissions rs
            JOIN exclusion_transitions et
              ON et.scope = 'run' AND et.scope_id = rs.run_id
             AND et.new_state = 'run_quarantined'
            WHERE rs.submission_id = NEW.submission_id
        ) THEN
            RAISE EXCEPTION 'submission belongs to a quarantined run'
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    CREATE TRIGGER digest_nominations_quarantine BEFORE INSERT ON digest_nominations
    FOR EACH ROW EXECUTE FUNCTION reject_quarantined_nomination();
END
$migration$;

INSERT INTO storage_schema_versions(version) VALUES (16) ON CONFLICT DO NOTHING;
