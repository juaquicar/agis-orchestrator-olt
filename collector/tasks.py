# collector/tasks.py
"""
Tareas Celery que:
1. Cargan la definición de OLTs desde config/olts.yaml
2. Sincronizan la tabla 'olt' en TimescaleDB/Postgres
3. Programan un sondeo periódico (PTX/PRX) por cada OLT
"""

import os
import datetime as dt
import logging
from typing import Dict, Any

from celery import Celery
from sqlalchemy.orm import Session
from sqlalchemy import text          #  ← AÑADE ESTA LÍNEA

from config import load_config        # lee YAML y aplica defaults
from db import get_engine

# ──────────────────────────────────────────────────────────────────────────────
# Dependencias de equipos (import condicional para que pytest no falle)
try:
    from jmq_olt_huawei import HuaweiOLT
    from jmq_olt_zyxel import ZyxelOLT
except ImportError:                    # en tests sin librerías
    HuaweiOLT = ZyxelOLT = None

# ──────────────────────────────────────────────────────────────────────────────
BROKER_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
DB_DSN = os.getenv("DB_DSN", "postgresql://postgres:changeme@db:5432/olt")

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

app = Celery("collector", broker=BROKER_URL)
engine = get_engine()

# Carga definición de OLTs una sola vez al arranque
OLTS: list[Dict[str, Any]] = load_config()

# ─────────────────── Helpers DB ───────────────────────────────────────────────
def sync_db():
    with Session(engine) as db:
        for cfg in OLTS:
            stmt = text("""
                INSERT INTO olt(id,vendor,host,port,username,password,
                                poll_interval,prompt,description)
                VALUES (:id,:vendor,:host,:port,:username,:password,
                        :pi,:prompt,:desc)
                ON CONFLICT (id) DO UPDATE SET
                    host=:host,
                    port=:port,
                    username=:username,
                    password=:password,
                    poll_interval=:pi,
                    prompt=:prompt,
                    description=:desc
            """)
            db.execute(stmt, dict(
                id       = cfg["id"],
                vendor   = cfg["vendor"],
                host     = cfg["host"],
                port     = cfg["port"],
                username = cfg["username"],
                password = cfg["password"],
                pi       = cfg["poll_interval"],
                prompt   = cfg["prompt"],
                desc     = cfg.get("description")
            ))
        db.commit()
# ─────────────────── Celery bootstrap ────────────────────────────────────────
@app.on_after_configure.connect
def setup_periodic(sender, **kwargs):
    """Se ejecuta una sola vez tras cargar el worker."""
    logging.info("Sincronizando tabla 'olt' con configuración YAML…")
    sync_db()

    for cfg in OLTS:
        sender.add_periodic_task(
            cfg["poll_interval"],
            poll_single_olt.s(cfg),
            name=f"poll_{cfg['id']}"
        )
        logging.info(
            "Programada tarea 'poll_%s' cada %s s",
            cfg["id"], cfg["poll_interval"]
        )

# ─────────────────── Tarea principal ─────────────────────────────────────────
@app.task
def poll_single_olt(cfg: Dict[str, Any]):
    """Sondea una OLT y almacena potencias."""

    vendor = cfg["vendor"]
    logging.info("Sondeando OLT %s (%s)…", cfg["id"], vendor)

    # 1. Instancia cliente según fabricante
    if vendor == "zyxel":
        client = ZyxelOLT(cfg["host"], cfg["username"], cfg["password"],
                          port=cfg["port"], prompt=cfg["prompt"])
    elif vendor == "huawei":
        client = HuaweiOLT(cfg["host"], cfg["username"], cfg["password"],
                           port=cfg["port"], prompt=cfg["prompt"])
    else:
        logging.error("Vendor no soportado: %s", vendor)
        return

    # 2. Obtiene lista de ONTs + potencias
    try:
        onts = client.get_onts()          # depende de la librería
    except Exception as exc:
        logging.exception("Fallo consultando %s: %s", cfg["id"], exc)
        return

    # 3. Inserta en BD
    now = dt.datetime.utcnow()
    rows = [(now, ont.id, ont.tx, ont.rx) for ont in onts]

    with Session(engine) as db:
        db.executemany(
            "INSERT INTO ont_power(time, ont_id, ptx, prx) VALUES (%s,%s,%s,%s)",
            rows
        )
        db.commit()
    logging.info("OLT %s → %d registros insertados", cfg["id"], len(rows))
