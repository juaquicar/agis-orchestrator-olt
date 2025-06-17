#!/usr/bin/env python3
"""
api_client.py ─ Cliente de línea de comandos para el OLT-Orchestrator
────────────────────────────────────────────────────────────────────
Instalación:
  pip install requests pandas click

Uso rápido:
  python api_client.py health
  python api_client.py geo -b "-3.80,40.38,-3.60,40.49"
  python api_client.py list --olt zyxel-central --limit 10
  python api_client.py history 123456 --hours 6 --csv potencias.csv
────────────────────────────────────────────────────────────────────
Variables de entorno admitidas:
  ORCH_API    URL base (por defecto http://localhost:8000)
  ORCH_TOKEN  Bearer token si tu API tiene auth
"""
from __future__ import annotations

import os
import json
from pathlib import Path
from datetime import datetime, timedelta

import click
import requests
import pandas as pd

BASE_URL = os.getenv("ORCH_API", "http://localhost:8000").rstrip("/")
TOKEN    = os.getenv("ORCH_TOKEN")   # opcional

print(BASE_URL, TOKEN)

# ─────────────────────── Helpers HTTP ────────────────────────
def api_get(path: str, params: dict | None = None):
    url = f"{BASE_URL}{path}"
    print(url)
    hdrs = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
    resp = requests.get(url, params=params, headers=hdrs, timeout=10)
    resp.raise_for_status()
    print(resp.json())
    return resp.json()


# ─────────────────────── CLI  –  click 🐍 ─────────────────────
@click.group()
def cli():
    pass


@cli.command()
def health():
    """Ping al servicio."""
    data = api_get("/health")
    click.echo(data)


@cli.command()
@click.option("-b", "--bbox", required=True,
              help="minLon,minLat,maxLon,maxLat (WGS-84)")
@click.option("--out", type=click.Path(), help="Guardar GeoJSON en fichero")
def geo(bbox: str, out: str | None):
    """GeoJSON de ONTs dentro del BBOX."""
    data = api_get("/geo", {"bbox": bbox})
    click.echo(f"Features: {len(data['features'])}")
    if out:
        Path(out).write_text(json.dumps(data, indent=2))
        click.echo(f"GeoJSON guardado en {out}")


@cli.command("list")
@click.option("--olt", help="Filtrar por ID de OLT")
@click.option("--limit", default=20, show_default=True)
def list_onts(olt: str | None, limit: int):
    """Listado paginado de ONTs + potencia actual."""
    params = {"limit": limit}
    if olt:
        params["olt_id"] = olt
    data = api_get("/onts", params)
    click.echo(f"Total ONTs: {data['total']}")
    for ont in data["items"]:
        click.echo(f"  {ont['id']}  "
                   f"{ont['olt_id']}  "
                   f"ptx={ont['ptx']}  prx={ont['prx']}")


@cli.command()
@click.argument("ont_id", type=int)
@click.option("--hours", default=24, show_default=True,
              help="Ventana de tiempo hacia atrás")
@click.option("--csv", type=click.Path(),
              help="Exportar la serie a CSV")
def history(ont_id: int, hours: int, csv: str | None):
    """Serie PTX/PRX de una ONT en las últimas `hours` horas."""
    since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    data = api_get(f"/onts/{ont_id}/history", {"hours": hours})

    df = pd.DataFrame(data)
    click.echo(df.head())

    if csv:
        df.to_csv(csv, index=False)
        click.echo(f"CSV guardado en {csv}")


if __name__ == "__main__":
    cli()
