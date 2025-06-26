
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
        SELECT
          o.id,
          o.olt_id,
          o.vendor_ont_id AS vendor_ont_id,
          o.serial,
          o.cto_uuid,
          ST_Y(o.geom) AS lat,
          ST_X(o.geom) AS lon,
          ST_AsGeoJSON(o.geom) AS geom
        FROM ont AS o
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
            features.append({
                "type": "Feature",
                "geometry": json.loads(r.geom),
                "properties": {
                    "ont_id": r.id,
                    "olt_id": r.olt_id,
                    "vendor_ont_id": r.vendor_ont_id,
                    "serial": r.serial,
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