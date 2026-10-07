"""osm_overpass: una consulta por categoría y por bbox de Japón (reglas/03).

Cada respuesta queda en <categoría>/<bbox>.json. Las bboxes se solapan: Silver
deduplica por id de OSM. En atlas_run cada consulta es su propia tarea (ver
_overpass.plan_queries); ingest() las corre en serie, para usar fuera del DAG.
"""

from __future__ import annotations

from pipeline.sources import _overpass
from pipeline.sources.base import BronzeRun
from pipeline.sources.registry import Registry, Source


def queries(registry: Registry, source: Source) -> list[tuple[str, str]]:
    config = registry.overpass
    bboxes = registry.japan_bboxes
    planned = []
    for category in source.params["categories"]:
        names = list(bboxes) if category["bboxes"] == "all" else category["bboxes"]
        for name in names:
            query = _overpass.build_query(
                category["selectors"],
                category["out"],
                timeout_s=config["timeout_s"],
                bbox=bboxes[name],
                snapshot_date=config["snapshot_date"],
            )
            planned.append((f"{category['id']}/{name}.json", query))
    return planned


def ingest(run: BronzeRun) -> None:
    for rel, query in queries(run.registry, run.source):
        _overpass.fetch(run, rel, query)


def finalize(run: BronzeRun) -> None:
    _overpass.finalize(run)
