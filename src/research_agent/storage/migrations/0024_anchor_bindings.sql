-- #325 (TDD-2.1.18): the anchor receiver storage is bound to. `bind-anchor`
-- inserts a row only after one verified round trip; the anchoring schedule
-- advances its last acknowledged head in place. A binding is never deleted,
-- its receiver never changes, and its acknowledged head never moves back
-- or changes hash at the same sequence.
CREATE TABLE IF NOT EXISTS anchor_bindings (
    receiver_url text PRIMARY KEY CHECK (receiver_url LIKE 'https://%'),
    verified_at timestamptz NOT NULL,
    last_acknowledged_sequence bigint NOT NULL
        CHECK (last_acknowledged_sequence >= 0),
    last_acknowledged_hash bytea NOT NULL
        CHECK (octet_length(last_acknowledged_hash) = 32),
    last_acknowledged_at timestamptz NOT NULL
);

CREATE OR REPLACE FUNCTION protect_anchor_binding() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.receiver_url <> OLD.receiver_url
       OR NEW.verified_at < OLD.verified_at
       OR NEW.last_acknowledged_at < OLD.last_acknowledged_at
       OR NEW.last_acknowledged_sequence < OLD.last_acknowledged_sequence
       OR (NEW.last_acknowledged_sequence = OLD.last_acknowledged_sequence
           AND NEW.last_acknowledged_hash <> OLD.last_acknowledged_hash) THEN
        RAISE EXCEPTION 'anchor binding acknowledgement cannot move back'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS anchor_bindings_monotonic ON anchor_bindings;
CREATE TRIGGER anchor_bindings_monotonic BEFORE UPDATE ON anchor_bindings
FOR EACH ROW EXECUTE FUNCTION protect_anchor_binding();

DROP TRIGGER IF EXISTS anchor_bindings_retained ON anchor_bindings;
CREATE TRIGGER anchor_bindings_retained BEFORE DELETE ON anchor_bindings
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

INSERT INTO storage_schema_versions(version) VALUES (24) ON CONFLICT DO NOTHING;
