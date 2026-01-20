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
from typing import Any, Dict, List, Optional

import yaml
from celery import Celery
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from config import STATUS_NORMALIZE

# ── APIs OLT ─────────────────────────────────────────────────
try:
    from jmq_olt_huawei.ma56xxt import APIMA56XXT, UserBusyError
except ImportError:
    APIMA56XXT = None

    class UserBusyError(Exception):
        pass

try:
    from jmq_olt_zyxel.OLT1408A import APIOLT1408A
    from jmq_olt_zyxel.OLT2406 import APIOLT2406
    from jmq_olt_zyxel.OLT1240XA import APIOLT1240XA
except ImportError as e:
    APIOLT1408A = APIOLT2406 = APIOLT1240XA = None
    print("IMPORT ERROR (librerías OLT Zyxel):", e)

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
    vendor = cfg["vendor"]

    if vendor == "zyxel1408A":
        if APIOLT1408A is None:
            raise ImportError("jmq_olt_zyxel no instalado (APIOLT1408A)")
        return APIOLT1408A(
            host=cfg["host"], port=cfg["port"],
            username=str(cfg["username"]), password=str(cfg["password"]),
            prompt=cfg["prompt"], timeout=timeout,
        )

    if vendor == "zyxel2406":
        if APIOLT2406 is None:
            raise ImportError("jmq_olt_zyxel no instalado (APIOLT2406)")
        return APIOLT2406(
            host=cfg["host"], port=cfg["port"],
            username=str(cfg["username"]), password=str(cfg["password"]),
            prompt=cfg["prompt"], timeout=timeout,
            debug=bool(cfg.get("debug", False)),
        )

    if vendor == "zyxel1240XA":
        if APIOLT1240XA is None:
            raise ImportError("jmq_olt_zyxel no instalado (APIOLT1240XA)")
        return APIOLT1240XA(
            host=cfg["host"], port=cfg["port"],
            username=str(cfg["username"]), password=str(cfg["password"]),
            prompt=cfg["prompt"], timeout=timeout,
            debug=bool(cfg.get("debug", False)),
        )

    if vendor == "huawei":
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
            debug=False,
        )

    raise ValueError(f"Vendor no soportado: {vendor}")

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

# ── Huawei scan ─────────────────────────────────────────────
from asgiref.sync import async_to_sync

def _scan_huawei(client, pon_list: List[Dict[str, Any]]) -> List[dict]:
    client.connect()

    onts: List[dict] = []
    for pon in pon_list:
        slot  = int(pon["slot"])
        port  = int(pon["port"])
        logging.debug("Huawei: escaneando %d/%d", slot, port)
        slice_onts = async_to_sync(client.get_onts)(slot, port)
        onts.extend(slice_onts)

    client.disconnect()
    return onts

# ── Zyxel 1240XA scan (filters/slots) ───────────────────────
def _scan_zyxel1240xa(client, filters: Optional[List[str]]) -> List[dict]:
    """
    En 1240XA se consulta por 'filter' (slots/tarjetas), ej: "1", "2".
    - Si no se pasa lista, se usa ["1"].
    - Se agrega el campo __filter para trazabilidad.
    """
    use_filters = filters or ["1"]

    all_onts: List[dict] = []
    for flt in use_filters:
        try:
            slice_onts = client.get_all_onts(str(flt))
            for o in slice_onts:
                o["__filter"] = str(flt)
            all_onts.extend(slice_onts)
        except Exception:
            logging.exception("1240XA: error leyendo filter=%s", flt)

    return all_onts

# ── Poll ────────────────────────────────────────────────────
@app.task
def poll_single_olt(cfg: Dict[str, Any]) -> None:
    vendor = cfg["vendor"]
    logging.info("Sondeando OLT %s (%s)…", cfg["id"], vendor)

    # 1 ▸ crear cliente
    try:
        client = build_client(cfg)
    except ImportError as exc:
        logging.error("Cliente no disponible: %s", exc)
        return

    # 2 ▸ consulta ONTs
    try:
        if vendor == "zyxel1408A":
            onts = client.get_all_onts()
        elif vendor == "zyxel2406":
            onts = client.get_all_onts()
            aids = [o.get("AID") for o in onts if o.get("AID")]
            logging.warning(
                "zyxel2406 %s → onts=%d aids_first=%s aids_last=%s",
                cfg["id"], len(onts), aids[:10], aids[-10:] if len(aids) >= 10 else aids
            )
        elif vendor == "zyxel1240XA":
            # soporta ambos nombres por compat:
            filters = cfg.get("filters") or cfg.get("slots")
            onts = _scan_zyxel1240xa(client, filters)
        elif vendor == "huawei":
            onts = _scan_huawei(client, cfg.get("pon_list", []))
        else:
            logging.warning("Vendor %s no localizado", vendor)
            return
    except UserBusyError:
        logging.warning("OLT %s ocupado, se reintentará", cfg["id"])
        return
    except Exception as exc:
        logging.exception("Error consultando %s: %s", cfg["id"], exc)
        return
    finally:
        # Cierre homogéneo si el cliente lo soporta (Zyxel suele exponer close()).
        try:
            if hasattr(client, "close"):
                client.close()
        except Exception:
            logging.debug("Cierre de sesión falló (ignorado)")

    # 3 ▸ construye filas con metadatos y potencias
    now = dt.datetime.utcnow()
    rows: List[Dict[str, Any]] = []

    def to_f(val: Any) -> float:
        try:
            if val is None:
                return 0.0
            return float(str(val).replace(" dBm", "").strip())
        except (TypeError, ValueError):
            return 0.0

    for ont in onts:
        if vendor == "huawei":
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

        elif vendor in ("zyxel1408A", "zyxel2406", "zyxel1240XA"):
            aid = ont.get("AID")
            if not aid:
                logging.debug("Descartado dict sin AID (%s): %s", vendor, ont)
                continue

            vid = aid

            # Normaliza status (puede venir como "IS", "Active", etc.)
            raw_status = ont.get("Status")
            raw_status_norm = str(raw_status).strip().upper() if raw_status is not None else None
            status = STATUS_NORMALIZE[vendor].get(raw_status_norm, 98)

            meta = {
                "AID":         aid,
                "Status":      raw_status,
                "SN":          ont.get("SN"),
                "Model":       ont.get("Model"),
                "__vendor":    vendor,
            }
            # trazabilidad de filter/slot en 1240XA
            if vendor == "zyxel1240XA" and "__filter" in ont:
                meta["filter"] = ont.get("__filter")

            # ptx/prx: por lo general Zyxel expone ONT Rx; ONT Tx puede no existir.
            ptx = to_f(ont.get("ONT Tx") or ont.get("tx") or ont.get("Tx") or ont.get("PTX"))
            prx = to_f(ont.get("ONT Rx") or ont.get("rx") or ont.get("Rx") or ont.get("PRX"))

            sn = ont.get("SN")
            model = ont.get("Model")
            description = ont.get("Description")

            # Campos extra en 1408A/2406 (no siempre presentes)
            if "Template-ID" in ont:
                meta["Template-ID"] = ont.get("Template-ID")
            if "FW Version" in ont:
                meta["FW Version"] = ont.get("FW Version")
            if "Distance" in ont:
                meta["Distance"] = ont.get("Distance")

        else:
            logging.warning("Vendor %s no soportado al procesar ONTs", vendor)
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
        # a) Prepara un dict por cada ONT única (dejamos el último)
        seen: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            seen[r["vendor_ont_id"]] = r

        # b) Upsert ONTs
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
                },
            )

        # c) Recupera mapping vendor_ont_id → PK ont.id
        mapping = dict(conn.execute(
            text("""
                SELECT vendor_ont_id, id
                  FROM ont
                 WHERE olt_id = :olt_id
                   AND vendor_ont_id = ANY(:vids)
            """),
            {"olt_id": cfg["id"], "vids": list(seen.keys())},
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
            if r["vendor_ont_id"] in mapping
        ]
        conn.execute(_INSERT_POWER, power_rows)

    logging.info("OLT %s → %d registros insertados", cfg["id"], len(rows))
