-- db-init/20260121_add_perf_indexes.sql
-- Para ejecutarse en /docker-entrypoint-initdb.d (inicialización de clúster).
-- NO usar CONCURRENTLY aquí para evitar fallos por transacciones implícitas.

-- 1) Índice espacial para bbox (ST_Intersects con envelope)
CREATE INDEX IF NOT EXISTS ont_geom_gist
  ON ont USING GIST (geom)
  WHERE geom IS NOT NULL;

-- 2) Índice para filtrar por olt_id
CREATE INDEX IF NOT EXISTS ont_olt_id_idx
  ON ont (olt_id);

-- 3) Índice para acelerar DISTINCT ON (ont_id) ORDER BY time DESC en ont_power
CREATE INDEX IF NOT EXISTS ont_power_last_idx
  ON ont_power (ont_id, time DESC)
  INCLUDE (ptx, prx, status);

ANALYZE ont;
ANALYZE ont_power;
