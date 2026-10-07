"""osm_summary (día 21): todo lo del atlas que viene de OpenStreetMap, por capa y
categoría, con su atribución. Los Pokémon Café del seed no cuentan: su fuente es la web
oficial (las coordenadas sí son de OSM)."""

from __future__ import annotations

from pathlib import Path

import duckdb

from pipeline.transforms.base import gold_path, write_entity

ATTRIBUTION = "© OpenStreetMap contributors (ODbL 1.0)"


def build(con: duckdb.DuckDBPyConnection, run_id: str, *, root: Path | None = None) -> dict:
    g = lambda entity: f"read_parquet('{gold_path(entity, root).as_posix()}')"  # noqa: E731
    query = f"""
        SELECT layer, category, elements, '{ATTRIBUTION}' AS attribution, 'ODbL-1.0' AS license
        FROM (
            SELECT 'poi' AS layer, category, count(*) AS elements FROM {g("poi")}
            WHERE source = 'osm' GROUP BY category
            UNION ALL SELECT 'rail', kind, count(*) FROM {g("rail")} GROUP BY kind
            UNION ALL SELECT 'station', 'station', count(*) FROM {g("station")}
            UNION ALL SELECT 'building', 'building', count(*) FROM {g("building")}
            UNION ALL SELECT 'shinkansen_route_stop', 'stop', count(*)
                      FROM {g("shinkansen_route_stop")}
        )
    """
    return write_entity(con, "osm_summary", query, root=root, layer="gold")
