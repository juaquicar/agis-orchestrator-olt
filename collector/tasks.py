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
import json
from typing import Any, Dict, List

import yaml
from celery import Celery
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from config import STATUS_NORMALIZE

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
DB_DSN      = os.getenv("DB_DSN", "postgresql://postgres:changeme@db:5432/olt")
CONFIG_PATH = os.getenv("OLT_CONFIG_PATH", "/config/olts.yaml")

app    = Celery("collector", broker=BROKER_URL)
engine = create_engine(DB_DSN, future=True, pool_pre_ping=True)

# ── SQL para upsert+select de ont y bulk insert en ont_power ──
_INSERT_POWER = text("""
    INSERT INTO ont_power(time, ont_id, ptx, prx, status)
    VALUES (:time, :ont_id, :ptx, :prx, :status)
""")

_UPSERT_ONT = text("""
    INSERT INTO ont(olt_id, vendor_ont_id, serial, model, description, status, props)
    VALUES (:olt_id, :vendor_ont_id, :serial, :model, :description, :status, CAST(:props AS jsonb))
    ON CONFLICT (olt_id, vendor_ont_id)
      DO UPDATE SET 
        status = EXCLUDED.status,
        props = EXCLUDED.props
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
    INSERT INTO olt(id, vendor, host, port, username, password,
                    poll_interval, prompt, description)
    VALUES (:id, :vendor, :host, :port, :username, :password,
            :pi, :prompt, :desc)
    ON CONFLICT (id) DO UPDATE SET
        host=:host, port=:port, username=:username, password=:password,
        poll_interval=:pi, prompt=:prompt, description=:desc
""")

def sync_db() -> None:
    with Session(engine) as db:
        for c in OLTS:
            db.execute(_INSERT_OLT, {
                "id": c["id"],
                "vendor": c["vendor"],
                "host": c["host"],
                "port": c["port"],
                "username": c["username"],
                "password": c["password"],
                "pi": c["poll_interval"],
                "prompt": c["prompt"],
                "desc": c.get("description"),
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
            host=cfg["host"],
            user=str(cfg["username"]),
            password=str(cfg["password"]),
            prompt=cfg["prompt"],
            snmp_ip=cfg["snmp_ip"],
            snmp_port=cfg["snmp_port"],
            snmp_community=cfg["snmp_community"],
            timeout=1,
            debug=False
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

from typing import List, Dict, Any
from asgiref.sync import async_to_sync

def _scan_huawei(client, pon_list: List[Dict[str, Any]]) -> List[dict]:
    # 1) abrir conexión Telnet / login
    client.connect()      # o el método que tu cliente exponga para inicializar self.tn

    onts: List[dict] = []
    for pon in pon_list:
        frame = str(pon["frame"])
        slot  = int(pon["slot"])
        port  = int(pon["port"])
        logging.debug("Huawei: escaneando %s/%d/%d", frame, slot, port)
        # ahora sí, get_onts ya tendrá self.tn != None
        print(f"Escaneando {slot}, {port}")
        slice = async_to_sync(client.get_onts)(slot, port)
        onts.extend(slice)

    # 2) cerrar sesión si tu cliente lo soporta
    client.disconnect()

    print(onts)
    return onts
@app.task
def poll_single_olt(cfg: Dict[str, Any]) -> None:
    logging.info("Sondeando OLT %s (%s)…", cfg["id"], cfg["vendor"])

    # 1 ▸ crear cliente
    try:
        client = build_client(cfg)
    except ImportError as exc:
        logging.error("Cliente no disponible: %s", exc)
        return

    # 2 ▸ consulta ONTs
    try:
        if cfg["vendor"] == "zyxel":
            onts = client.get_all_onts()
        elif cfg["vendor"] == "huawei":
            onts = _scan_huawei(client, cfg.get("pon_list", []))
        else:
            logging.warning("Vendor %s no localizado", cfg["vendor"])
            return
    except UserBusyError:
        logging.warning("OLT %s ocupado, se reintentará", cfg["id"])
        return
    except Exception as exc:
        logging.exception("Error consultando %s: %s", cfg["id"], exc)
        return

    # 3 ▸ construye filas con metadatos y potencias
    now = dt.datetime.utcnow()
    rows: List[Dict[str, Any]] = []

    def to_f(val: Any) -> float:
        try:
            return float(val)
        except (TypeError, ValueError):
            return 0.0

    for ont in onts:
        if cfg["vendor"] == "huawei":
            vid = f"{ont.get('schema_fsp')}/{ont.get('id')}"
            meta = {
                "id":           vid,
                "schema_fsp":   ont.get("schema_fsp"),
                "control_flag": ont.get("control_flag"),
                "run_state":    ont.get("run_state"),
                "config_state": ont.get("config_state"),
                "match_state":  ont.get("match_state"),
                "protect_side": ont.get("protect_side"),
            }
            ptx = to_f(ont.get("ptx") or ont.get("tx"))
            prx = to_f(ont.get("prx") or ont.get("rx"))
            status = STATUS_NORMALIZE["huawei"].get(ont.get("run_state"), 98)
            sn = ont.get("sn")
            model = None
            description = ont.get("description")

        elif cfg["vendor"] == "zyxel":
            aid = ont.get("AID")
            if not aid:
                logging.debug("Descartado dict sin AID (Zyxel): %s", ont)
                continue
            vid = aid
            meta = {
                "AID":          aid,
                "Status":       ont.get("Status"),
                "Template-ID":  ont.get("Template-ID"),
                "FW Version":   ont.get("FW Version"),
                "Distance":     ont.get("Distance"),
            }
            ptx = float(ont.get("ONT Tx") or ont.get("tx") or 0)
            prx = float(ont.get("ONT Rx") or ont.get("rx") or 0)
            status = STATUS_NORMALIZE["zyxel"].get(ont.get("Status"), 98)
            sn = ont.get("SN")
            model = ont.get("Model")
            description = ont.get("Description")

        else:
            logging.warning("Vendor %s no soportado al procesar ONTs", cfg["vendor"])
            continue

        rows.append({
            "time":          now,
            "vendor_ont_id": vid,
            "ptx":           ptx,
            "prx":           prx,
            "status":        status,
            "serial":        sn,
            "model":         model,
            "description":   description,
            "props":         json.dumps(meta),
        })

    if not rows:
        logging.warning("OLT %s devolvió 0 ONTs", cfg["id"])
        return

    # 4 ▸ upsert en ont y bulk insert en ont_power
    with engine.begin() as conn:
        # a) Prepara un dict por cada ONT única
        seen: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            # dejamos la última fila de cada vendor_ont_id
            seen[r["vendor_ont_id"]] = r

        # b) Upsert con todos los campos necesarios
        for vid, r in seen.items():
            conn.execute(
                _UPSERT_ONT,
                {
                    "olt_id":        cfg["id"],
                    "vendor_ont_id": vid,
                    "serial":        r["serial"],
                    "model":         r["model"],
                    "description":   r["description"],
                    "status":        r["status"],
                    "props":         r["props"],
                }
            )

        # c) Recupera mapping vendor_ont_id → PK ont.id
        mapping = dict(conn.execute(
            text("""
                SELECT vendor_ont_id, id
                  FROM ont
                 WHERE olt_id = :olt_id
                   AND vendor_ont_id = ANY(:vids)
            """),
            {"olt_id": cfg["id"], "vids": list(seen.keys())}
        ).all())

        # d) Inserta batch de potencias
        power_rows = [
            {
                "time":   r["time"],
                "ont_id": mapping[r["vendor_ont_id"]],
                "ptx":    r["ptx"],
                "prx":    r["prx"],
                "status": r["status"],
            }
            for r in rows
        ]
        conn.execute(_INSERT_POWER, power_rows)

    logging.info("OLT %s → %d registros insertados", cfg["id"], len(rows))