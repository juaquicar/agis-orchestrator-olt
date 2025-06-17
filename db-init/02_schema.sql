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
--  Catálogo de OLTs (sin cambios)
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
--  Catálogo de CTOs  (sin cambios)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cto (
    uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    label TEXT,
    geom  geometry(Point, 4326)           -- lat/lon WGS-84
);
CREATE INDEX IF NOT EXISTS cto_geom_gix
    ON cto USING GIST (geom);

-- ─────────────────────────────────────────────────────────────
--  Catálogo de ONTs (versión genérica)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ont (
    id               BIGSERIAL   PRIMARY KEY,                -- surrogate key interno
    olt_id           TEXT        NOT NULL
                                REFERENCES olt(id)  ON DELETE CASCADE,
    vendor_ont_id    TEXT        NOT NULL,                   -- ID real que devuelve la API
    cto_uuid         UUID        REFERENCES cto(uuid) ON DELETE SET NULL,
    geom             geometry(Point, 4326),                  -- posición individual (NULL si hereda CTO)
    serial           TEXT,
    model            TEXT,
    UNIQUE (olt_id, vendor_ont_id)
);

CREATE INDEX IF NOT EXISTS ont_geom_gix
    ON ont USING GIST (geom);

-- ─────────────────────────────────────────────────────────────
--  Histórico de potencias (PTX/PRX) por ONT (sin cambios)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ont_power (
    time   TIMESTAMPTZ NOT NULL,
    ont_id BIGINT       NOT NULL
                         REFERENCES ont(id)
                         ON DELETE CASCADE,
    ptx    NUMERIC,                         -- dBm transmitido
    prx    NUMERIC,                         -- dBm recibido
    PRIMARY KEY (time, ont_id)
);

-- Convierte en hypertable (TimescaleDB)
SELECT create_hypertable(
    'ont_power','time',
    if_not_exists => TRUE,
    migrate_data  => TRUE
);
