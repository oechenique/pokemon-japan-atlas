"""center_to_shinkansen (día 24): cada Pokémon Center con su estación del Shinkansen más
cercana, en línea recta sobre la esfera. Muestra qué ciudades con Pokémon Center conecta
la red (Okinawa, por ejemplo, queda lejos de todas)."""

from __future__ import annotations

from pathlib import Path

import duckdb

from pipeline.transforms.base import gold_path, write_entity


def build(con: duckdb.DuckDBPyConnection, run_id: str, *, root: Path | None = None) -> dict:
    poi = gold_path("poi", root).as_posix()
    stations = gold_path("shinkansen_stations", root).as_posix()
    query = f"""
        WITH pairs AS (
            SELECT c.poi_id, c.name_ja AS center_name, s.station_key, s.name_ja AS station_name,
                   ST_Distance_Sphere(c.geometry, s.geometry) / 1000 AS distance_km,
                   ST_MakeLine(c.geometry, s.geometry) AS geometry
            FROM read_parquet('{poi}') c, read_parquet('{stations}') s
            WHERE c.category = 'pokemon_center'
        )
        SELECT poi_id, center_name, station_key, station_name, distance_km,
               'ODbL-1.0' AS license, geometry
        FROM pairs
        QUALIFY row_number() OVER (PARTITION BY poi_id ORDER BY distance_km, station_key) = 1
    """
    return write_entity(con, "center_to_shinkansen", query, root=root, layer="gold")
