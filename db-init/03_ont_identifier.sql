/* db-init/03_add_identifier.sql  ─ añade identificador textual */
ALTER TABLE ont
  ADD COLUMN IF NOT EXISTS identifier text;

-- mantén la unicidad por OLT + identifier
CREATE UNIQUE INDEX IF NOT EXISTS ont_olt_identifier_uq
  ON ont(olt_id, identifier);