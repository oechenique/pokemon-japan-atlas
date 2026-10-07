"""shinkansen_edges (día 24): tramos entre estaciones consecutivas del listado oficial.

Un tramo por par de estaciones vecinas en alguna línea (el sentido no importa); lines
junta las líneas que lo comparten (por ejemplo, Tōhoku, Jōetsu y Hokuriku entre Tokio
y Ōmiya). La geometría es la recta entre las estaciones: el grafo es esquemático.
schematic marca los tramos de los mini-Shinkansen (Akita, Yamagata), que no tienen vía
del Shinkansen en el mapa porque corren por vías convencionales; en los demás, la vía
real está en rail.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from pipeline.transforms.base import gold_path, write_entity

LICENSE = "LicenseRef-seeds + ODbL-1.0"


def build(con: duckdb.DuckDBPyConnection, run_id: str, *, root: Path | None = None) -> dict:
    line_station = gold_path("shinkansen_line_station", root).as_posix()
    query = f"""
        WITH ordered AS (
            SELECT line_id, kind, seq, name_ja, geometry,
                   lead(name_ja) OVER (PARTITION BY line_id ORDER BY seq) AS next_name,
                   lead(geometry) OVER (PARTITION BY line_id ORDER BY seq) AS next_geometry
            FROM read_parquet('{line_station}')
        ),
        pairs AS (
            SELECT least(name_ja, next_name) AS a, greatest(name_ja, next_name) AS b,
                   line_id, kind,
                   CASE WHEN name_ja < next_name THEN geometry ELSE next_geometry END AS ga,
                   CASE WHEN name_ja < next_name THEN next_geometry ELSE geometry END AS gb
            FROM ordered WHERE next_name IS NOT NULL
        )
        SELECT 'shinkansen:' || a || '|shinkansen:' || b AS edge_id,
               'shinkansen:' || a AS from_key, 'shinkansen:' || b AS to_key,
               list(DISTINCT line_id ORDER BY line_id) AS lines,
               CASE WHEN bool_and(kind = 'mini') THEN 'mini' ELSE 'full' END AS kind,
               bool_and(kind = 'mini') AS schematic,
               ST_Distance_Sphere(any_value(ga), any_value(gb)) / 1000 AS distance_km,
               '{LICENSE}' AS license,
               ST_MakeLine(any_value(ga), any_value(gb)) AS geometry
        FROM pairs GROUP BY a, b
    """
    summary = write_entity(con, "shinkansen_edges", query, root=root, layer="gold")
    written = gold_path("shinkansen_edges", root).as_posix()
    by_kind = dict(con.execute(f"SELECT kind, count(*) FROM '{written}' GROUP BY 1").fetchall())
    return {**summary, "stats": {f"edges_{k}": v for k, v in sorted(by_kind.items())}}
