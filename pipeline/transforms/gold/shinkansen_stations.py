"""shinkansen_stations (día 24): estaciones del Shinkansen, una por nombre.

Salen de shinkansen_line_station: el listado oficial de JR por línea, cruzado con los
nodos de OSM. lines junta las líneas de cada estación; kind es mini solo si todas sus
líneas son mini (Morioka y Fukushima son full: también las cruza el Tōhoku).

El método anterior (relaciones de ruta de OSM y distancia a la vía) quedó descartado:
las rutas solo cubren el Tōhoku y la distancia perdía Niigata y sumaba convencionales
pegadas al viaducto.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from pipeline.transforms.base import gold_path, write_entity

LICENSE = "LicenseRef-seeds + ODbL-1.0"


def build(con: duckdb.DuckDBPyConnection, run_id: str, *, root: Path | None = None) -> dict:
    line_station = gold_path("shinkansen_line_station", root).as_posix()
    query = f"""
        SELECT 'shinkansen:' || name_ja AS station_key, min(station_id) AS station_id, name_ja,
               list(DISTINCT line_id ORDER BY line_id) AS lines,
               CASE WHEN bool_and(kind = 'mini') THEN 'mini' ELSE 'full' END AS kind,
               min(prefecture_code) AS prefecture_code, '{LICENSE}' AS license,
               arg_min(geometry, station_id) AS geometry
        FROM read_parquet('{line_station}')
        GROUP BY name_ja
    """
    summary = write_entity(con, "shinkansen_stations", query, root=root, layer="gold")
    written = gold_path("shinkansen_stations", root).as_posix()
    by_kind = dict(con.execute(f"SELECT kind, count(*) FROM '{written}' GROUP BY 1").fetchall())
    return {**summary, "stats": {f"stations_{k}": v for k, v in sorted(by_kind.items())}}
