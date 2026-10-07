"""Gold (reglas/03): copias de Silver aprobado por el DQ gate, tablas derivadas y vistas.

- Las 12 entidades de Silver pasan a data/gold/<entidad>.parquet como enlace (hardlink;
  copia si el sistema de archivos no deja). Los rasters no se copian: raster_product
  sigue apuntando a data/silver/rasters/.
- Las tablas derivadas tienen su módulo en pipeline/transforms/gold/<tabla>.py y su
  contrato en pipeline/contracts/gold/. Leen siempre de Gold, nunca de Silver.
- Las vistas gold.v_day_XX viven en data/gold/atlas.duckdb (ver gold/views.py).
"""

from __future__ import annotations

import importlib
import os
import shutil
from pathlib import Path
from typing import Any

from pipeline.sources.base import sha256_file
from pipeline.transforms.base import connect, gold_path, silver_path
from pipeline.transforms.silver_entities import DEPENDENCIES as SILVER_ENTITIES

# tabla derivada -> tablas derivadas que tienen que estar antes.
DERIVED: dict[str, tuple[str, ...]] = {
    "poi_clusters": (),
    "fuji_viewshed": (),
    "power_plants_kanto": (),
    "center_nearest_station": (),
    "shinkansen_stations": (),
    "shinkansen_edges": ("shinkansen_stations",),
    "center_to_shinkansen": ("shinkansen_stations",),
    "null_findings": (),
    "null_rates_by_prefecture": (),
    "osm_summary": (),
}


def copy_silver(run_id: str, *, root: Path | None = None) -> list[dict[str, Any]]:
    """Pasa a Gold el Silver que aprobó el DQ gate."""
    summaries = []
    for entity in sorted(SILVER_ENTITIES):
        source = silver_path(entity, root)
        target = gold_path(entity, root)
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(target.name + ".part")
        part.unlink(missing_ok=True)
        try:
            os.link(source, part)
        except OSError:
            shutil.copyfile(source, part)
        os.replace(part, target)
        summaries.append(
            {
                "entity": entity,
                "kind": "silver_copy",
                "run_id": run_id,
                "bytes": target.stat().st_size,
                "sha256": sha256_file(target),
                "path": f"gold/{entity}.parquet",
            }
        )
    return summaries


def build_derived(table: str, run_id: str, *, root: Path | None = None) -> dict[str, Any]:
    if table not in DERIVED:
        raise KeyError(f"tabla de Gold desconocida: {table}")
    module = importlib.import_module(f"pipeline.transforms.gold.{table}")
    con = connect()
    try:
        summary = module.build(con, run_id, root=root)
    finally:
        con.close()
    return {**summary, "kind": "derived", "run_id": run_id}
