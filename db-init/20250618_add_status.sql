-- db-init/20250618_add_status.sql
BEGIN;

-- 1) Añadimos status a ont
ALTER TABLE ont
  ADD COLUMN status TEXT;

-- 2) Añadimos status a ont_power
ALTER TABLE ont_power
  ADD COLUMN status TEXT;

COMMIT;
