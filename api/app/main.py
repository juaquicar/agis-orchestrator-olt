
# main.py (FastAPI)
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import List, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from .database import get_db  # helper para AsyncSession


from fastapi.middleware.cors import CORSMiddleware
from .agis_client import _get_agis_token, fetch_cto_list, fetch_cto_geojson
from fastapi import HTTPException
from fastapi import Path, Body


app = FastAPI(
    title="OLT Orchestrator API",
    version="0.1.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ───────────────────────── PING ────────────────────────────
@app.get("/health", tags=["misc"])
async def health() -> Dict[str, str]:
    return {"status": "ok"}

# ───────────────────────── GEOJSON ─────────────────────────
def parse_bbox(bbox: str) -> List[float]:
    try:
        minx, miny, maxx, maxy = map(float, bbox.split(","))
    except ValueError:
        raise HTTPException(400, "bbox debe ser 'minLon,minLat,maxLon,maxLat'")
    if minx >= maxx or miny >= maxy:
        raise HTTPException(400, "bbox inválido")
    return [minx, miny, maxx, maxy]

@app.get(
    "/geo",
    tags=["geo"],
    summary="Geometría de ONTs en BBOX",
    response_description="GeoJSON FeatureCollection"
)
async def geo(
    bbox: str = Query(
        ..., example="-3.80,40.38,-3.60,40.49",
        description="minLon,minLat,maxLon,maxLat"
    ),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    minx, miny, maxx, maxy = parse_bbox(bbox)
    sql = text("""
        WITH last AS (
            SELECT DISTINCT ON (ont_id)
              ont_id,
              time,
              ptx,
              prx,
              status AS power_status
            FROM ont_power
            ORDER BY ont_id, time DESC
        )
        SELECT
          o.id,
          o.olt_id,
          o.vendor_ont_id       AS vendor_ont_id,
          o.status              AS status,
          o.cto_uuid,
          o.description,
          o.model,
          o.serial,
          ST_Y(o.geom)          AS lat,
          ST_X(o.geom)          AS lon,
          ST_AsGeoJSON(o.geom)  AS geom,
          o.props,
          l.ptx,
          l.prx,
          l.time                AS last_read,
          l.power_status
        FROM ont AS o
        JOIN last AS l
          ON l.ont_id = o.id
        WHERE 
          o.geom IS NOT NULL
          AND ST_Intersects(
                o.geom,
                ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326)
              )
    """)
    result = await db.execute(sql, {"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy})
    rows = result.fetchall()

    features: List[Dict[str, Any]] = []
    for r in rows:
        if r.geom:
            features.append({ # Vamos a hacer el objeto lo más parecido al local
                "type": "Feature",
                "geometry": json.loads(r.geom),
                "properties": {
                    "id": r.id,
                    "ont_id": r.id,
                    "olt_id": r.olt_id,
                    "external_id": r.id,
                    "vendor_ont_id": r.vendor_ont_id,
                    "external_name": r.vendor_ont_id,
                    "model": r.model,
                    "sn": r.serial,
                    "state": r.status,
                    "topology": r.cto_uuid,
                    "cto_uuid": r.cto_uuid,
                    "description": r.description,
                    "props": r.props,
                    "metrics": {
                        "ptx": r.ptx,
                        "prx": r.prx,
                    }
                },
            })
    return {"type": "FeatureCollection", "features": features}

# ──────────────────────── MODELOS API ───────────────────────
class Ont(BaseModel):
    id: int
    olt_id: str
    vendor_ont_id: str
    ptx: float | None = None
    prx: float | None = None
    status: int
    serial: str | None = None
    model: str | None = None
    description: str | None = None
    cto_uuid: str | None = None
    lat: float | None = None
    lon: float | None = None
    last_read: datetime = Field(..., description="Timestamp de la última lectura")
    props: Dict[str, Any] = Field(
        ..., description="Metadatos originales de la ONT (status, SN, modelo, …)"
    )

class OntList(BaseModel):
    total: int
    items: List[Ont]

class Point(BaseModel):
    time: datetime
    ptx: float | None = Field(None, example=-22.5)
    prx: float | None = Field(None, example=-26.8)
    status: str | None =  Field(None, example=1)

# ──────────────────── LISTADO DE ONTs ───────────────────────
@app.get(
    "/onts",
    response_model=OntList,
    tags=["onts"],
    summary="Listado de ONTs con última potencia, timestamp y props"
)
async def list_onts(
    limit: int = Query(20, le=1000),
    offset: int = 0,
    olt_id: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> OntList:
    where_clause = "WHERE o.olt_id = :olt" if olt_id else ""
    sql = text(f"""
        WITH last AS (
            SELECT DISTINCT ON (ont_id) ont_id, time, ptx, prx, status
              FROM ont_power
             ORDER BY ont_id, time DESC
        )
        SELECT
          o.id,
          o.olt_id,
          o.vendor_ont_id AS vendor_ont_id,
          o.status,
          o.cto_uuid,
          o.serial,
          o.model,
          o.description,
          ST_Y(o.geom) AS lat,
          ST_X(o.geom) AS lon,
          l.ptx,
          l.prx,
          l.time   AS last_read,
          o.props
        FROM ont AS o
        JOIN last AS l ON l.ont_id = o.id
        {where_clause}
        ORDER BY o.id
        LIMIT :lim OFFSET :off
    """)
    result = await db.execute(sql, {"lim": limit, "off": offset, "olt": olt_id})
    rows = result.fetchall()

    items = [
        Ont(
            id=r.id,
            olt_id=r.olt_id,
            vendor_ont_id=r.vendor_ont_id,
            ptx=r.ptx,
            prx=r.prx,
            status=r.status,
            lat=r.lat,
            lon=r.lon,
            cto_uuid=r.cto_uuid,
            serial=r.serial,
            model=r.model,
            description=r.description,
            last_read=r.last_read,
            props=r.props,
        ) for r in rows
    ]
    total = await db.scalar(
        text("SELECT COUNT(*) FROM ont" + (" WHERE olt_id=:olt" if olt_id else "")),
        {"olt": olt_id}
    )
    return OntList(total=total or 0, items=items)

# ─────────────── SERIE TEMPORAL PTX/PRX ─────────────────────
@app.get(
    "/onts/{ont_id}/history",
    response_model=list[Point],
    tags=["onts"],
    summary="Serie de potencias de una ONT"
)
async def ont_history(
    ont_id: int,
    hours: int = Query(24, gt=0, le=24*30),
    db: AsyncSession = Depends(get_db),
) -> list[Point]:
    since = datetime.utcnow() - timedelta(hours=hours)
    sql = text("""
        SELECT time, ptx, prx, status
          FROM ont_power
         WHERE ont_id = :oid
           AND time >= :since
         ORDER BY time DESC
    """)
    result = await db.execute(sql, {"oid": ont_id, "since": since})
    rows = result.fetchall()
    if not rows:
        raise HTTPException(404, "ONT sin datos")
    return [Point(time=r.time, ptx=r.ptx, prx=r.prx, status=r.status) for r in rows]


# ─────────────── UBICAR Y UUID POR ADMIN-UI ─────────────────────

class OntPatch(BaseModel):
    cto_uuid: str | None = None
    lon: float | None = None
    lat: float | None = None

@app.patch("/onts/{ont_id}", tags=["onts"])
async def patch_ont(
    ont_id: int = Path(..., description="ID interno de la ONT"),
    patch: OntPatch = Body(...),
    db: AsyncSession = Depends(get_db),
):
    # Solo consideramos los campos realmente enviados
    patch_data = patch.dict(exclude_unset=True)
    updates = []
    params = {"id": ont_id}

    # Actualizar cto_uuid (incluso si es None)
    if "cto_uuid" in patch_data:
        updates.append("cto_uuid = :cto_uuid")
        params["cto_uuid"] = patch_data["cto_uuid"]

    # Actualizar geom si vienen lat y lon
    if "lon" in patch_data and "lat" in patch_data:
        updates.append("geom = ST_SetSRID(ST_Point(:lon, :lat),4326)")
        params["lon"] = patch_data["lon"]
        params["lat"] = patch_data["lat"]

    if not updates:
        raise HTTPException(status_code=400, detail="Nada que actualizar")

    sql = text(f"UPDATE ont SET {', '.join(updates)} WHERE id = :id")
    await db.execute(sql, params)
    await db.commit()
    return {"ok": True}



#################
#  AGIS
#################


@app.get("/ctos/list", tags=["ctos"])
async def cto_list():
    try:
        return await fetch_cto_list()
    except Exception as e:
        raise HTTPException(502, f"Error AGIS list: {e}")

@app.get("/ctos/geojson", tags=["ctos"])
async def cto_geojson():
    try:
        return await fetch_cto_geojson()
    except Exception as e:
        raise HTTPException(502, f"Error AGIS geojson: {e}")



######################
# METRICS TIMESERIES #
######################


class OntMetricBase(BaseModel):
    ont_id: int
    metric: str
    value: float | None
    timestamp: datetime

    model_config = dict(from_attributes=True)  # ORM mode

class OntMetricResponse(OntMetricBase):
    pass  # aquí podrías añadir un campo `id` si lo necesitas

# ─── Endpoint /metrics/ para PTX/PRX/STATUS de ONT ────────────────────────────

@app.get(
    "/metrics/",
    response_model=List[OntMetricResponse],
    summary="Serie temporal de métricas (ptx/prx/status) de una ONT",
    tags=["metrics"],
)
async def get_ont_metrics(
    ont_id: int = Query(..., description="ID interno de la ONT"),
    metric: str = Query(
        ...,
        regex="^(ptx|prx|status)$",
        description="Métrica a consultar: 'ptx', 'prx' o 'status'",
    ),
    start: datetime = Query(..., description="Fecha/hora de inicio (ISO8601)"),
    end: datetime = Query(..., description="Fecha/hora de fin (ISO8601)"),
    db: AsyncSession = Depends(get_db),
) -> List[OntMetricResponse]:
    """
    Serie temporal cruda de una métrica de ont_power para una ONT (sin agregación).
    """
    sql = text("""
        SELECT
          ont_id         AS ont_id,
          :metric        AS metric,
          CASE
            WHEN :metric = 'ptx'    THEN ptx
            WHEN :metric = 'prx'    THEN prx
            WHEN :metric = 'status' THEN status::DOUBLE PRECISION
          END            AS value,
          time           AS timestamp
        FROM ont_power
        WHERE ont_id = :ont_id
          AND time BETWEEN :start AND :end
        ORDER BY time ASC
    """)
    params = {"metric": metric, "ont_id": ont_id, "start": start, "end": end}
    result = await db.execute(sql, params)
    rows = result.fetchall()
    return [OntMetricResponse(**r._mapping) for r in rows]


### Nuevas APIs para ADMIN-UI que no alteran las anteriores que usa aGIS.

from typing import Optional

class UIItem(BaseModel):
    id: str
    name: str

class UIList(BaseModel):
    items: List[UIItem]

class UIOntItem(BaseModel):
    id: int
    olt_id: str
    olt_name: str
    vendor_ont_id: str
    pon_id: str
    cto_uuid: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    status: Optional[int] = None
    serial: Optional[str] = None
    model: Optional[str] = None
    description: Optional[str] = None

class UIOntList(BaseModel):
    total: int
    items: List[UIOntItem]


def sql_pon_id_expr() -> str:
    """
    Deriva el 'pon_id' a partir de ont.vendor_ont_id + olt.vendor.
    - huawei:        CHASIS/SLOT/PON/ID -> CHASIS/SLOT/PON
    - zyxel2406/1240XA: (ont-)SLOT-PON-ID -> SLOT-PON
    - zyxel1408A:    (ont-)PON-ID -> PON
    Nota: se elimina prefijo ^ont- si existe.
    """
    return r"""
    CASE
      WHEN ol.vendor = 'huawei' THEN
        split_part(o.vendor_ont_id, '/', 1) || '/' ||
        split_part(o.vendor_ont_id, '/', 2) || '/' ||
        split_part(o.vendor_ont_id, '/', 3)

      WHEN ol.vendor IN ('zyxel2406','zyxel1240XA') THEN
        split_part(regexp_replace(o.vendor_ont_id, '^ont-', ''), '-', 1) || '-' ||
        split_part(regexp_replace(o.vendor_ont_id, '^ont-', ''), '-', 2)

      WHEN ol.vendor IN ('zyxel1408A','zyxel') THEN
        split_part(regexp_replace(o.vendor_ont_id, '^ont-', ''), '-', 1)

      ELSE
        -- fallback: si tiene '/', asume huawei-like; si tiene '-', usa primer token
        CASE
          WHEN position('/' in o.vendor_ont_id) > 0 THEN
            split_part(o.vendor_ont_id, '/', 1) || '/' ||
            split_part(o.vendor_ont_id, '/', 2) || '/' ||
            split_part(o.vendor_ont_id, '/', 3)
          ELSE
            split_part(regexp_replace(o.vendor_ont_id, '^ont-', ''), '-', 1)
        END
    END
    """


@app.get("/ui/olts", response_model=UIList, tags=["ui"], summary="Listado de OLTs (admin-ui)")
async def ui_list_olts(db: AsyncSession = Depends(get_db)) -> UIList:
    sql = text("""
        SELECT
          id::text AS id,
          COALESCE(NULLIF(description,''), id)::text AS name
        FROM olt
        ORDER BY id
    """)
    res = await db.execute(sql)
    items = [UIItem(id=r.id, name=r.name) for r in res.fetchall()]
    return UIList(items=items)


@app.get("/ui/olts/{olt_id}/pons", response_model=UIList, tags=["ui"], summary="Listado de PONs por OLT (derivado)")
async def ui_list_pons(
    olt_id: str,
    db: AsyncSession = Depends(get_db),
) -> UIList:
    pon_expr = sql_pon_id_expr()
    sql = text(f"""
        SELECT DISTINCT
          ({pon_expr})::text AS id,
          ({pon_expr})::text AS name
        FROM ont o
        JOIN olt ol ON ol.id = o.olt_id
        WHERE o.olt_id = :olt_id
        ORDER BY id
    """)
    res = await db.execute(sql, {"olt_id": olt_id})
    items = [UIItem(id=r.id, name=r.name) for r in res.fetchall()]
    return UIList(items=items)


@app.get(
    "/ui/onts",
    response_model=UIOntList,
    tags=["ui"],
    summary="Listado paginado de ONTs filtrado por OLT+PON (pensado para 'sin ubicar')",
)
async def ui_list_onts(
    olt_id: str = Query(..., description="ID de la OLT"),
    pon_id: str = Query(..., description="ID de PON derivado (selector)"),
    only_unlocated: int = Query(0, description="1 para solo ONTs sin geom (geom IS NULL)"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> UIOntList:
    pon_expr = sql_pon_id_expr()

    where_unlocated = "AND o.geom IS NULL" if only_unlocated == 1 else ""

    sql_items = text(f"""
        SELECT
          o.id,
          o.olt_id,
          COALESCE(NULLIF(ol.description,''), ol.id)::text AS olt_name,
          o.vendor_ont_id,
          ({pon_expr})::text AS pon_id,
          o.cto_uuid,
          ST_Y(o.geom) AS lat,
          ST_X(o.geom) AS lon,
          o.status,
          o.serial,
          o.model,
          o.description
        FROM ont o
        JOIN olt ol ON ol.id = o.olt_id
        WHERE o.olt_id = :olt_id
          AND ({pon_expr})::text = :pon_id
          {where_unlocated}
        ORDER BY o.id
        LIMIT :lim OFFSET :off
    """)

    sql_total = text(f"""
        SELECT COUNT(*)
        FROM ont o
        JOIN olt ol ON ol.id = o.olt_id
        WHERE o.olt_id = :olt_id
          AND ({pon_expr})::text = :pon_id
          {where_unlocated}
    """)

    params = {"olt_id": olt_id, "pon_id": pon_id, "lim": limit, "off": offset}

    res = await db.execute(sql_items, params)
    rows = res.fetchall()

    total = await db.scalar(sql_total, {"olt_id": olt_id, "pon_id": pon_id})

    items = [
        UIOntItem(
            id=r.id,
            olt_id=r.olt_id,
            olt_name=r.olt_name,
            vendor_ont_id=r.vendor_ont_id,
            pon_id=r.pon_id,
            cto_uuid=r.cto_uuid,
            lat=r.lat,
            lon=r.lon,
            status=r.status,
            serial=r.serial,
            model=r.model,
            description=r.description,
        )
        for r in rows
    ]
    return UIOntList(total=int(total or 0), items=items)

@app.get(
    "/ui/onts/geo",
    tags=["ui"],
    summary="GeoJSON de ONTs en BBOX filtrado por OLT+PON (admin-ui)",
    response_description="GeoJSON FeatureCollection"
)
async def ui_geo_onts(
    bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat"),
    olt_id: str | None = Query(None, description="ID de la OLT"),
    pon_id: str | None = Query(None, description="ID de la PON derivada"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    # Protección de rendimiento: sin OLT+PON -> vacío
    if not olt_id or not pon_id:
        return {"type": "FeatureCollection", "features": []}

    minx, miny, maxx, maxy = parse_bbox(bbox)
    pon_expr = sql_pon_id_expr()

    sql = text(f"""
        SELECT
          o.id,
          o.olt_id,
          COALESCE(NULLIF(ol.description,''), ol.id)::text AS olt_name,
          o.vendor_ont_id,
          ({pon_expr})::text AS pon_id,
          o.status,
          o.cto_uuid,
          o.description,
          o.model,
          o.serial,
          ST_AsGeoJSON(o.geom) AS geom
        FROM ont o
        JOIN olt ol ON ol.id = o.olt_id
        WHERE o.geom IS NOT NULL
          AND o.olt_id = :olt_id
          AND ({pon_expr})::text = :pon_id
          AND ST_Intersects(
                o.geom,
                ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326)
              )
        ORDER BY o.id
    """)

    res = await db.execute(sql, {
        "minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy,
        "olt_id": olt_id, "pon_id": pon_id
    })
    rows = res.fetchall()

    features: List[Dict[str, Any]] = []
    for r in rows:
        if not r.geom:
            continue
        features.append({
            "type": "Feature",
            "geometry": json.loads(r.geom),
            "properties": {
                "ont_id": r.id,
                "id": r.id,
                "olt_id": r.olt_id,
                "olt_name": r.olt_name,
                "pon_id": r.pon_id,
                "vendor_ont_id": r.vendor_ont_id,
                "status": r.status,
                "cto_uuid": r.cto_uuid,
                "description": r.description,
                "model": r.model,
                "serial": r.serial,
            }
        })

    return {"type": "FeatureCollection", "features": features}

# ───────────────────────── UI ADMIN: UNLOCATED TREE ─────────────────────────

class UIPonGroup(BaseModel):
    id: str
    name: str
    count: int

class UIOltGroup(BaseModel):
    olt_id: str
    olt_name: str
    count: int
    pons: List[UIPonGroup]

class UIUnlocatedGroups(BaseModel):
    items: List[UIOltGroup]

@app.get(
    "/ui/unlocated/groups",
    response_model=UIUnlocatedGroups,
    tags=["ui"],
    summary="Jerarquía OLT->PON con counts de ONTs sin ubicar (geom IS NULL)",
)
async def ui_unlocated_groups(db: AsyncSession = Depends(get_db)) -> UIUnlocatedGroups:
    pon_expr = sql_pon_id_expr()

    # OJO: repetimos la expresión de olt_name en GROUP BY (no alias)
    sql = text(f"""
        SELECT
          o.olt_id::text AS olt_id,
          COALESCE(NULLIF(ol.description,''), ol.id)::text AS olt_name,
          ({pon_expr})::text AS pon_id,
          COUNT(*)::int AS cnt
        FROM ont o
        JOIN olt ol ON ol.id = o.olt_id
        WHERE o.geom IS NULL
        GROUP BY
          o.olt_id,
          COALESCE(NULLIF(ol.description,''), ol.id),
          ({pon_expr})
        ORDER BY o.olt_id, pon_id
    """)

    res = await db.execute(sql)
    rows = res.fetchall()

    tree: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        key = r.olt_id
        if key not in tree:
            tree[key] = {"olt_id": r.olt_id, "olt_name": r.olt_name, "count": 0, "pons": []}
        tree[key]["pons"].append({"id": r.pon_id, "name": r.pon_id, "count": r.cnt})
        tree[key]["count"] += r.cnt

    items = [UIOltGroup(**v) for v in tree.values()]
    return UIUnlocatedGroups(items=items)

