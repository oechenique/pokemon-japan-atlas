"""Entidades de Silver que construye atlas_run, con sus dependencias entre sí.

Cada entidad tiene su módulo en pipeline/transforms/silver/<entidad>.py con una
función build(con, bronze, root=...). El orden importa solo donde una entidad lee
otra de Silver (game_region usa las geometrías de prefecture).
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from pipeline.transforms.base import Bronze, connect

# entidad -> entidades de Silver que tienen que estar antes.
DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "prefecture": (),
    "game_region": ("prefecture",),
    "game_place": (),
    "outside_region": (),
    "poi": ("prefecture", "game_region"),
    "rail": (),
    "station": ("prefecture",),
    "building": (),
    "raster_product": (),
    "basemap": (),
    "shinkansen_route_stop": ("station",),
    "shinkansen_line_station": ("station", "rail"),
    "h3_metric": ("prefecture", "poi", "rail"),
}


def build_entity(entity: str, run_id: str, *, root: Path | None = None) -> dict[str, Any]:
    if entity not in DEPENDENCIES:
        raise KeyError(f"entidad de Silver desconocida: {entity}")
    module = importlib.import_module(f"pipeline.transforms.silver.{entity}")
    con = connect()
    try:
        summary = module.build(con, Bronze(run_id, root), root=root)
    finally:
        con.close()
    return {**summary, "run_id": run_id}
