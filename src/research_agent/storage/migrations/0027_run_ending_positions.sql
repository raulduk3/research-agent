-- #327: a run ending's place in the ledger's one total order, so the live
-- run stream can page trace calls, terminals, endings and settlements by a
-- single cursor. Calls, terminals and settlements carry their own
-- ledger_sequence; run_terminal_states does not. Each writer of an ending
-- appends its ledger record in the same transaction and holds the ledger
-- head until commit, so the head read at commit is that record: no
-- transaction can commit a later sequence first. Endings recorded before
-- this migration have no position and are not in the stream.

CREATE TABLE IF NOT EXISTS run_ending_positions (
    run_id uuid PRIMARY KEY REFERENCES run_terminal_states(run_id) ON DELETE RESTRICT,
    ledger_sequence bigint NOT NULL REFERENCES ledger_records(sequence) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS run_ending_positions_ledger_sequence_idx
    ON run_ending_positions(ledger_sequence);

DROP TRIGGER IF EXISTS run_ending_positions_immutable ON run_ending_positions;
CREATE TRIGGER run_ending_positions_immutable BEFORE UPDATE OR DELETE ON run_ending_positions
FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

CREATE OR REPLACE FUNCTION record_run_ending_position() RETURNS trigger AS $$
BEGIN
    INSERT INTO run_ending_positions(run_id, ledger_sequence)
    SELECT NEW.run_id, sequence FROM ledger_head WHERE singleton FOR UPDATE;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS run_terminal_states_position ON run_terminal_states;
CREATE CONSTRAINT TRIGGER run_terminal_states_position
AFTER INSERT ON run_terminal_states
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION record_run_ending_position();

INSERT INTO storage_schema_versions(version) VALUES (27) ON CONFLICT DO NOTHING;
