"""game_place: lugares del juego y el lugar real que los inspiró (día 8), del seed.

Coordenadas del ítem de Wikidata del lugar real (CC0); celdas H3 de resolución 7 y 9.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from pipeline.transforms.base import Bronze, write_entity

LICENSE = "LicenseRef-seeds + CC0-1.0"


def build(con: duckdb.DuckDBPyConnection, bronze: Bronze, *, root: Path | None = None) -> dict:
    seed = bronze.path("seeds", "game_places.csv")
    query = f"""
        SELECT place_id, game_name, region_id, real_place, real_place_wikidata,
               prefecture_code, confidence, source_url,
               list_filter(string_split(coalesce(other_sources, ''), ' '), x -> x <> '')
                   AS other_sources,
               nullif(notes, '') AS notes,
               h3_latlng_to_cell_string(lat::DOUBLE, lon::DOUBLE, 7) AS h3_r7,
               h3_latlng_to_cell_string(lat::DOUBLE, lon::DOUBLE, 9) AS h3_r9,
               '{LICENSE}' AS license,
               ST_Point(lon::DOUBLE, lat::DOUBLE) AS geometry
        FROM read_csv('{seed}', all_varchar = true)
    """
    return write_entity(con, "game_place", query, root=root)
