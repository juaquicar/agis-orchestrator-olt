Variante (para BD ya existente en producción/desarrollo): CONCURRENTLY

Este NO se pondría en db-init si ya hay datos; se ejecutas “a mano” con psql.

Guárdalo como: 20260121_add_perf_indexes_concurrent.sql (fuera de db-init si quieres) y ejecútalo manualmente.

```sql
-- 20260121_add_perf_indexes_concurrent.sql
-- Para aplicar en caliente (BD ya existente).
-- Debe ejecutarse FUERA de transacciones explícitas.

SET lock_timeout = '5s';
SET statement_timeout = '0';

CREATE INDEX CONCURRENTLY IF NOT EXISTS ont_geom_gist
  ON ont USING GIST (geom)
  WHERE geom IS NOT NULL;

CREATE INDEX CONCURRENTLY IF NOT EXISTS ont_olt_id_idx
  ON ont (olt_id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS ont_power_last_idx
  ON ont_power (ont_id, time DESC)
  INCLUDE (ptx, prx, status);

ANALYZE ont;
ANALYZE ont_power;
```

Cómo ejecutarlo en el contenedor DB

Con el mapeo 5433:5432, desde el host:
```bash
psql "postgresql://postgres:${POSTGRES_PASSWORD}@localhost:5433/${POSTGRES_DB}" \
  -f 20260121_add_perf_indexes_concurrent.sql
```