"""building: edificios de OSM alrededor del Pokémon Center Mega Tokyo (día 14).

- Vías cerradas: un polígono por vía.
- Relaciones (multipolígonos): las vías outer y las inner se poligonizan por separado y
  se resta inner de outer.
- Todo pasa por ST_MakeValid; lo que queda vacío o no es polígono se descarta y se
  cuenta para el DQ gate.
- height_m y levels se leen solo si el tag es numérico (por ejemplo "187" o "52").
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from pipeline.transforms import osm
from pipeline.transforms.base import Bronze, write_entity

LICENSE = "ODbL-1.0"
NUMBER = r"^\s*([0-9]+(\.[0-9]+)?)\s*(m)?\s*$"


def build(con: duckdb.DuckDBPyConnection, bronze: Bronze, *, root: Path | None = None) -> dict:
    files = [bronze.path("osm_buildings", "buildings.json")]
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE osm_building AS
        SELECT (e ->> 'type') || '/' || (e ->> 'id') AS osm_key, e ->> 'type' AS osm_type, e
        FROM (SELECT unnest(elements) AS e
              FROM read_json([{", ".join(f"'{f}'" for f in files)}],
                             columns = {{elements: 'JSON[]'}},
                             maximum_object_size = {osm.max_object_size(files)}))
        QUALIFY row_number() OVER (PARTITION BY (e ->> 'type') || '/' || (e ->> 'id')) = 1
    """)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE building_shapes AS
        WITH way_lines AS (
            SELECT osm_key, e, {osm.line_sql("e -> 'geometry'")} AS line
            FROM osm_building
            WHERE osm_type = 'way' AND json_array_length(e -> 'geometry') >= 4
        ),
        ways AS (
            SELECT osm_key, e, ST_MakeValid(ST_MakePolygon(line)) AS geometry
            FROM way_lines WHERE ST_IsClosed(line)
        ),
        members AS (
            SELECT osm_key, m ->> 'role' AS role, {osm.line_sql("m -> 'geometry'")} AS line
            FROM (SELECT osm_key, unnest(CAST(e -> 'members' AS JSON[])) AS m
                  FROM osm_building WHERE osm_type = 'relation')
            WHERE json_array_length(m -> 'geometry') >= 2
        ),
        rings AS (
            SELECT osm_key,
                   ST_Polygonize(list(line) FILTER (WHERE role = 'outer')) AS outer_area,
                   ST_Polygonize(list(line) FILTER (WHERE role = 'inner')) AS inner_area
            FROM members GROUP BY osm_key
        ),
        relations AS (
            SELECT b.osm_key, b.e,
                   ST_MakeValid(CASE WHEN r.inner_area IS NULL OR ST_IsEmpty(r.inner_area)
                                     THEN r.outer_area
                                     ELSE ST_Difference(r.outer_area, r.inner_area) END)
                       AS geometry
            FROM osm_building b JOIN rings r USING (osm_key)
        )
        SELECT osm_key, e, ST_CollectionExtract(geometry, 3) AS geometry FROM ways
        UNION ALL
        SELECT osm_key, e, ST_CollectionExtract(geometry, 3) AS geometry FROM relations
    """)
    total, kept = con.execute("""
        SELECT (SELECT count(*) FROM osm_building),
               count(*) FILTER (WHERE geometry IS NOT NULL AND NOT ST_IsEmpty(geometry))
        FROM building_shapes
    """).fetchone()
    stats = {"osm_elements_unique": total, "buildings_dropped_invalid": total - kept}
    query = f"""
        SELECT 'osm:' || osm_key AS building_id,
               {osm.tag("building")} AS building,
               coalesce({osm.tag("name:ja")}, {osm.tag("name")}) AS name,
               CASE WHEN regexp_matches({osm.tag("height")}, '{NUMBER}')
                    THEN regexp_extract({osm.tag("height")}, '{NUMBER}', 1)::DOUBLE END AS height_m,
               CASE WHEN regexp_matches({osm.tag("building:levels")}, '^\\s*[0-9]+\\s*$')
                    THEN trim({osm.tag("building:levels")})::INTEGER END AS levels,
               '{LICENSE}' AS license,
               ST_SetCRS(ST_Multi(geometry), 'OGC:CRS84') AS geometry
        FROM building_shapes
        WHERE geometry IS NOT NULL AND NOT ST_IsEmpty(geometry)
    """
    summary = write_entity(con, "building", query, root=root)
    return {**summary, "stats": stats}
