"""osm_buildings: edificios de OSM alrededor de un solo punto (día 14, reglas/03).

Una consulta `around` centrada en el Pokémon Center Mega Tokyo. En atlas_run comparte
el pool de Overpass con osm_overpass (ver _overpass.plan_queries).
"""

from __future__ import annotations

from pipeline.sources import _overpass
from pipeline.sources.base import BronzeRun
from pipeline.sources.registry import Registry, Source


def queries(registry: Registry, source: Source) -> list[tuple[str, str]]:
    config = registry.overpass
    params = source.params
    center = params["center"]
    query = _overpass.build_query(
        params["selectors"],
        params["out"],
        timeout_s=config["timeout_s"],
        around=(params["radius_m"], center["lat"], center["lon"]),
        snapshot_date=config["snapshot_date"],
    )
    return [("buildings.json", query)]


def ingest(run: BronzeRun) -> None:
    for rel, query in queries(run.registry, run.source):
        _overpass.fetch(run, rel, query)


def finalize(run: BronzeRun) -> None:
    _overpass.finalize(run, center=run.source.params["center"])
