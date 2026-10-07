"""center_nearest_station (día 13): cada Pokémon Center y su estación más cercana.

Distancia en línea recta sobre la esfera (ST_Distance_Sphere). La búsqueda se limita a
0,1° (~10 km); la geometría es el tramo recto entre el centro y la estación.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from pipeline.transforms.base import gold_path, write_entity

SEARCH_DEG = 0.1


def build(con: duckdb.DuckDBPyConnection, run_id: str, *, root: Path | None = None) -> dict:
    poi = gold_path("poi", root).as_posix()
    station = gold_path("station", root).as_posix()
    query = f"""
        WITH centers AS (
            SELECT poi_id, name_ja, game_region, geometry FROM read_parquet('{poi}')
            WHERE category = 'pokemon_center'
        ),
        pairs AS (
            SELECT c.poi_id, c.name_ja AS center_name, c.game_region, c.geometry AS c_geom,
                   s.station_id, s.name_ja AS station_name, s.geometry AS s_geom,
                   ST_Distance_Sphere(c.geometry, s.geometry) AS distance_m
            FROM centers c
            JOIN read_parquet('{station}') s ON ST_DWithin(c.geometry, s.geometry, {SEARCH_DEG})
        )
        SELECT poi_id, center_name, station_id, station_name, distance_m, game_region,
               'ODbL-1.0' AS license, ST_MakeLine(c_geom, s_geom) AS geometry
        FROM pairs
        QUALIFY row_number() OVER (PARTITION BY poi_id ORDER BY distance_m, station_id) = 1
    """
    return write_entity(con, "center_nearest_station", query, root=root, layer="gold")
