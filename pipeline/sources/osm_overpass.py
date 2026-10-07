"""osm_overpass: una consulta por categoría y por bbox de Japón (reglas/03).

Cada respuesta queda en <categoría>/<bbox>.json. Las bboxes se solapan: Silver
deduplica por id de OSM.
"""

from __future__ import annotations

from pipeline.sources import _overpass
from pipeline.sources.base import BronzeRun


def ingest(run: BronzeRun) -> None:
    config = run.registry.overpass
    bboxes = run.registry.japan_bboxes
    run.extra["snapshot_date"] = config["snapshot_date"]
    for category in run.source.params["categories"]:
        names = list(bboxes) if category["bboxes"] == "all" else category["bboxes"]
        for name in names:
            query = _overpass.build_query(
                category["selectors"],
                category["out"],
                timeout_s=config["timeout_s"],
                bbox=bboxes[name],
                snapshot_date=config["snapshot_date"],
            )
            _overpass.fetch(run, f"{category['id']}/{name}.json", query)
