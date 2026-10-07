"""osm_buildings: edificios de OSM alrededor de un solo punto (día 14, reglas/03).

Una consulta `around` centrada en el Pokémon Center Mega Tokyo.
"""

from __future__ import annotations

from pipeline.sources import _overpass
from pipeline.sources.base import BronzeRun


def ingest(run: BronzeRun) -> None:
    config = run.registry.overpass
    params = run.source.params
    center = params["center"]
    run.extra["center"] = center
    run.extra["snapshot_date"] = config["snapshot_date"]
    query = _overpass.build_query(
        params["selectors"],
        params["out"],
        timeout_s=config["timeout_s"],
        around=(params["radius_m"], center["lat"], center["lon"]),
        snapshot_date=config["snapshot_date"],
    )
    _overpass.fetch(run, "buildings.json", query)
