# collector/tasks.py
# ───────────────────────────────────────────────────────────────
# • Lee config/olts.yaml
# • Sincroniza la tabla `olt`
# • Programa una tarea periódica por OLT
# • Guarda potencias en ont_power (TimescaleDB/PostGIS)
# ───────────────────────────────────────────────────────────────

from __future__ import annotations

import os
import logging
import datetime as dt
from typing import Any, Dict, List

import yaml
from celery import Celery
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

# ── APIs OLT ─────────────────────────────────────────────────
try:
    from jmq_olt_huawei.ma56xxt import APIMA56XXT, UserBusyError
    from jmq_olt_zyxel.OLT1408A import APIOLT1408A
except ImportError as e:
    APIMA56XXT = APIOLT1408A = None
    print("IMPORT ERROR (librerías OLT):", e)

# ── Config global ───────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

BROKER_URL  = os.getenv("REDIS_URL", "redis://redis:6379/0")
DB_DSN      = os.getenv("DB_DSN",
                        "postgresql://postgres:changeme@db:5432/olt")
CONFIG_PATH = os.getenv("OLT_CONFIG_PATH", "/config/olts.yaml")

app    = Celery("collector", broker=BROKER_URL)
engine = create_engine(DB_DSN, future=True, pool_pre_ping=True)

# ── SQL para upsert+select de ont y bulk insert en ont_power ──
_INSERT_ONT = text("""
    INSERT INTO ont(olt_id, vendor_ont_id)
    VALUES (:olt_id, :vendor_ont_id)
    ON CONFLICT (olt_id, vendor_ont_id) DO NOTHING
""")
# (no hace falta SELECT por cada fila; lo haremos en bloque)
_INSERT_POWER = text("""
    INSERT INTO ont_power(time, ont_id, ptx, prx)
    VALUES (:time, :ont_id, :ptx, :prx)
""")

# ── YAML ────────────────────────────────────────────────────
def load_config() -> List[Dict[str, Any]]:
    with open(CONFIG_PATH, "r") as f:
        raw = yaml.safe_load(f)

    defaults = raw.get("defaults", {})
    out: List[Dict[str, Any]] = []
    for olt in raw.get("olts", []):
        cfg = defaults.copy()
        cfg.update(olt)
        out.append(cfg)
    return out


OLTS = load_config()

# ── Sync tabla olt ──────────────────────────────────────────
_INSERT_OLT = text("""
    INSERT INTO olt(id,vendor,host,port,username,password,
                    poll_interval,prompt,description)
    VALUES (:id,:vendor,:host,:port,:username,:password,
            :pi,:prompt,:desc)
    ON CONFLICT (id) DO UPDATE SET
        host=:host, port=:port, username=:username, password=:password,
        poll_interval=:pi, prompt=:prompt, description=:desc
""")

def sync_db() -> None:
    with Session(engine) as db:
        for c in OLTS:
            db.execute(_INSERT_OLT, {
                "id": c["id"], "vendor": c["vendor"], "host": c["host"],
                "port": c["port"], "username": c["username"],
                "password": c["password"], "pi": c["poll_interval"],
                "prompt": c["prompt"], "desc": c.get("description"),
            })
        db.commit()

# ── Factoría de clientes ───────────────────────────────────
def build_client(cfg: Dict[str, Any]):
    timeout = cfg.get("timeout", 5)

    if cfg["vendor"] == "zyxel":
        if APIOLT1408A is None:
            raise ImportError("jmq_olt_zyxel no instalado")
        return APIOLT1408A(
            host=cfg["host"], port=cfg["port"],
            username=str(cfg["username"]), password=str(cfg["password"]),
            prompt=cfg["prompt"], timeout=timeout,
        )

    if cfg["vendor"] == "huawei":
        if APIMA56XXT is None:
            raise ImportError("jmq_olt_huawei no instalado")
        return APIMA56XXT(
            host=cfg["host"], port=cfg["port"],
            username=str(cfg["username"]), password=str(cfg["password"]),
            prompt=cfg["prompt"], timeout=timeout,
        )

    raise ValueError(f"Vendor no soportado: {cfg['vendor']}")

# ── Arranque Celery ─────────────────────────────────────────
@app.on_after_configure.connect
def setup_periodic(sender, **_):
    logging.info("Sincronizando tabla 'olt'…")
    sync_db()

    for c in OLTS:
        sender.add_periodic_task(
            c["poll_interval"],
            poll_single_olt.s(c),
            name=f"poll_{c['id']}",
        )
        logging.info("Programada 'poll_%s' cada %s s", c["id"], c["poll_interval"])

# ── Tarea principal ─────────────────────────────────────────
@app.task
def poll_single_olt(cfg: Dict[str, Any]) -> None:
    logging.info("Sondeando OLT %s (%s)…", cfg["id"], cfg["vendor"])

    try:
        client = build_client(cfg)
    except ImportError as exc:
        logging.error("Cliente no disponible: %s", exc)
        return

    # 1 ▸ consulta ONTs
    try:
        onts = client.get_all_onts() if cfg["vendor"] == "zyxel" else client.get_onts()
    except UserBusyError:
        logging.warning("OLT %s ocupado, se reintentará", cfg["id"])
        return
    except Exception as exc:
        logging.exception("Error consultando %s: %s", cfg["id"], exc)
        return

    # 2 ▸ construye filas (manteniendo vendor_ont_id separado)
    now = dt.datetime.utcnow()
    rows: List[Dict[str, Any]] = []

    for ont in onts:
        if isinstance(ont, dict):  # Zyxel
            aid = ont.get("AID")
            if not aid:
                logging.debug("Descartado dict sin AID: %s", ont)
                continue

            ptx = ont.get("tx") or ont.get("ONT Tx") or ont.get("ptx") or 0
            prx = ont.get("rx") or ont.get("ONT Rx") or ont.get("prx") or 0

            rows.append({
                "time": now,
                "vendor_ont_id": str(aid),  # <-- aquí usamos AID
                "ptx": float(ptx),
                "prx": float(prx),
            })
        else:  # Huawei (objeto)
            vid = str(ont.id)
            rows.append({
                "time": now,
                "vendor_ont_id": vid,
                "ptx": float(getattr(ont, "tx", getattr(ont, "ptx", 0))),
                "prx": float(getattr(ont, "rx", getattr(ont, "prx", 0))),
            })

    if not rows:
        logging.warning("OLT %s devolvió 0 ONTs", cfg["id"])
        return

    # 3 ▸ upsert en ont y bulk insert en ont_power
    with engine.begin() as conn:
        # a) Upsert de todas las ONTs en bloque
        unique_vids = list({r["vendor_ont_id"] for r in rows})
        for vid in unique_vids:
            conn.execute(
                _INSERT_ONT,
                {"olt_id": cfg["id"], "vendor_ont_id": vid}
            )

        # b) Recupera el mapping vendor_ont_id → id
        mapping = dict(conn.execute(
            text("""
                SELECT vendor_ont_id, id
                  FROM ont
                 WHERE olt_id = :olt_id
                   AND vendor_ont_id = ANY(:vids)
            """),
            {"olt_id": cfg["id"], "vids": unique_vids}
        ).all())

        # c) Prepara y lanza el bulk insert en ont_power
        power_rows = [
            {
                "time":     r["time"],
                "ont_id":   mapping[r["vendor_ont_id"]],
                "ptx":      r["ptx"],
                "prx":      r["prx"],
            }
            for r in rows
        ]
        conn.execute(_INSERT_POWER, power_rows)

    logging.info("OLT %s → %d registros insertados", cfg["id"], len(power_rows))
