-- 2025xx_add_props_and_last_read.sql

BEGIN;

-- 1. Añadimos props para metadatos arbitrarios de cada ONT
ALTER TABLE ont
  ADD COLUMN props JSONB NOT NULL DEFAULT '{}'::jsonb;

-- (Opcional) índice GIN para búsquedas sobre props
CREATE INDEX ON ont USING GIN (props);

COMMIT;
