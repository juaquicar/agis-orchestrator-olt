/* db-init/02_schema.sql
 * ------------------------------------------------------------------
 *  Esquema mínimo para el servicio OLT-Orchestrator.
 *  Se ejecuta al primer arranque del contenedor `db`
 *  (volumen nuevo) gracias a docker-entrypoint-initdb.d.
 * ------------------------------------------------------------------
 *  Requiere que 01_extensions.sql haya creado:
 *      - extension timescaledb
 *      - extension postgis
 * ------------------------------------------------------------------
 */

-- ─────────────────────────────────────────────────────────────
--  Catálogo de OLTs
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS olt (
    id            TEXT PRIMARY KEY,                           -- p.e. 'zyxel-central'
    vendor        TEXT NOT NULL CHECK (vendor IN ('huawei','zyxel')),
    host          TEXT NOT NULL,
    port          INT  NOT NULL,
    username      TEXT,
    password      TEXT,
    poll_interval INT  NOT NULL DEFAULT 300,                  -- seg
    prompt        TEXT,
    description   TEXT
);

-- ─────────────────────────────────────────────────────────────
--  Catálogo de CTOs  (opcional, pero útil para geometría)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cto (
    uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    label TEXT,
    geom  geometry(Point, 4326)           -- lat/lon WGS-84
);

-- Índice espacial para búsquedas rápidas
CREATE INDEX IF NOT EXISTS cto_geom_gix
    ON cto USING GIST (geom);

-- ─────────────────────────────────────────────────────────────
--  Catálogo de ONTs
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ont (
    id        BIGINT PRIMARY KEY,            -- serial/ID único del equipo
    olt_id    TEXT    REFERENCES olt(id),
    cto_uuid  UUID    REFERENCES cto(uuid) ON DELETE SET NULL,
    geom      geometry(Point, 4326),         -- posición individual (NULL si hereda CTO)
    serial    TEXT,
    model     TEXT
);

CREATE INDEX IF NOT EXISTS ont_geom_gix
    ON ont USING GIST (geom);

-- ─────────────────────────────────────────────────────────────
--  Histórico de potencias (PTX/PRX) por ONT
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ont_power (
    time   TIMESTAMPTZ NOT NULL,
    ont_id BIGINT       REFERENCES ont(id)
                         ON DELETE CASCADE,
    ptx    NUMERIC,                         -- dBm transmitido
    prx    NUMERIC,                         -- dBm recibido
    PRIMARY KEY (time, ont_id)
);

-- Convierte en hypertable (TimescaleDB)
SELECT create_hypertable('ont_power','time',
                         if_not_exists => TRUE,
                         migrate_data  => TRUE);

/* ─────────────────────────────────────────────────────────────
   𝗙𝗶𝗻  del esquema
   Podrás añadir tablas de auditoría, continuous aggregates,
   índices adicionales, etc., mediante futuras migraciones.
   ───────────────────────────────────────────────────────────── */
