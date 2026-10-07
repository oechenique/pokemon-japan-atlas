"""Lectura de OSM desde Bronze, compartida por poi, rail, station y building.

- Las respuestas de Overpass se leen como JSON (los tags varían demasiado entre
  elementos para inferir un esquema) y se extrae solo lo que usa cada entidad.
- Deduplicación por id de OSM: las bbox se solapan y un elemento puede venir varias
  veces. Si aparece en más de una categoría, gana la primera de `precedence`. Los
  descartes se cuentan para el DQ gate.
- Prefectura de un punto: la que lo contiene (`within`) o, si cae al mar por la
  resolución de Natural Earth, la más cercana a menos de ~5 km (`nearest`, 0,05°).
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import PurePosixPath

import duckdb

from pipeline.transforms.base import Bronze, silver_path

# Margen sobre el archivo más grande al fijar maximum_object_size: DuckDB reserva
# buffers de ese tamaño por hilo, así que un valor fijo grande agota la memoria.
OBJECT_MARGIN_BYTES = 1024 * 1024
NEAREST_DEGREES = 0.05


def overpass_files(bronze: Bronze, source_id: str, categories: Sequence[str]) -> list[str]:
    """Rutas de Bronze de las categorías pedidas (<categoría>/<bbox>.json)."""
    files = [f["path"] for f in bronze.metadata(source_id)["files"]]
    wanted = [f for f in files if PurePosixPath(f).parts[0] in categories]
    missing = set(categories) - {PurePosixPath(f).parts[0] for f in wanted}
    if missing:
        from pipeline.transforms.base import TransformError

        raise TransformError(f"{source_id}: faltan categorías {sorted(missing)} en Bronze")
    return [bronze.path(source_id, f) for f in sorted(wanted)]


def load_elements(
    con: duckdb.DuckDBPyConnection,
    table: str,
    files: Sequence[str],
    precedence: Sequence[str] | None = None,
) -> dict[str, int]:
    """Tabla temporal con un elemento por id de OSM: category, osm_key, osm_type, e (JSON).

    La categoría sale de la carpeta del archivo. Devuelve los conteos de la
    deduplicación.
    """
    file_list = ", ".join(f"'{f}'" for f in files)
    order = (
        "CASE category "
        + " ".join(f"WHEN '{c}' THEN {i}" for i, c in enumerate(precedence))
        + " END"
        if precedence
        else "0"
    )
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE {table}_raw AS
        SELECT regexp_extract(filename, '/([a-z_]+)/[a-z_]+\\.json$', 1) AS category,
               unnest(elements) AS e
        FROM read_json([{file_list}], columns = {{elements: 'JSON[]'}}, filename = true,
                       maximum_object_size = {max_object_size(files)})
    """)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE {table} AS
        SELECT category,
               (e ->> 'type') || '/' || (e ->> 'id') AS osm_key,
               e ->> 'type' AS osm_type,
               e
        FROM {table}_raw
        QUALIFY row_number() OVER (
            PARTITION BY (e ->> 'type') || '/' || (e ->> 'id')
            ORDER BY {order}, category
        ) = 1
    """)
    raw, unique = con.execute(
        f"SELECT (SELECT count(*) FROM {table}_raw), (SELECT count(*) FROM {table})"
    ).fetchone()
    same_category = con.execute(f"""
        SELECT coalesce(sum(n - 1), 0) FROM (
            SELECT count(*) AS n FROM {table}_raw
            GROUP BY category, (e ->> 'type') || '/' || (e ->> 'id')
        )
    """).fetchone()[0]
    con.execute(f"DROP TABLE {table}_raw")
    return {
        "osm_elements_raw": raw,
        "osm_elements_unique": unique,
        "osm_duplicates_overlapping_bboxes": int(same_category),
        "osm_duplicates_across_categories": raw - unique - int(same_category),
    }


def max_object_size(files: Sequence[str]) -> int:
    """maximum_object_size para read_json: el archivo más grande más un margen."""
    return max(os.path.getsize(f) for f in files) + OBJECT_MARGIN_BYTES


def point_sql(alias: str = "e") -> str:
    """Punto de un elemento: lat/lon del nodo o el centro de la vía o relación."""
    lat = f"coalesce(({alias} ->> 'lat')::DOUBLE, ({alias} -> 'center' ->> 'lat')::DOUBLE)"
    lon = f"coalesce(({alias} ->> 'lon')::DOUBLE, ({alias} -> 'center' ->> 'lon')::DOUBLE)"
    return f"ST_SetCRS(ST_Point({lon}, {lat}), 'OGC:CRS84')"


def line_sql(path: str) -> str:
    """LineString desde un arreglo JSON de {lat, lon} (out geom de Overpass)."""
    points = f"CAST({path} AS STRUCT(lat DOUBLE, lon DOUBLE)[])"
    return (
        f"ST_SetCRS(ST_MakeLine(list_transform({points}, p -> ST_Point(p.lon, p.lat))), "
        "'OGC:CRS84')"
    )


def tag(name: str, alias: str = "e") -> str:
    return f"nullif(trim({alias} -> 'tags' ->> '{name}'), '')"


def assign_prefecture(
    con: duckdb.DuckDBPyConnection, points_table: str, key: str, root=None
) -> dict[str, int]:
    """Agrega prefecture_code y prefecture_method a points_table (key, geometry)."""
    prefecture = silver_path("prefecture", root).as_posix()
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE {points_table}_pref AS
        WITH pref AS (SELECT prefecture_code, geometry FROM read_parquet('{prefecture}')),
        within AS (
            SELECT p.{key}, min(pref.prefecture_code) AS prefecture_code
            FROM {points_table} p JOIN pref ON ST_Within(p.geometry, pref.geometry)
            GROUP BY p.{key}
        ),
        nearest AS (
            SELECT p.{key},
                   arg_min(pref.prefecture_code, ST_Distance(p.geometry, pref.geometry))
                       AS prefecture_code
            FROM {points_table} p
            JOIN pref ON ST_DWithin(p.geometry, pref.geometry, {NEAREST_DEGREES})
            WHERE p.{key} NOT IN (SELECT {key} FROM within)
            GROUP BY p.{key}
        )
        SELECT {key}, prefecture_code, 'within' AS prefecture_method FROM within
        UNION ALL
        SELECT {key}, prefecture_code, 'nearest' AS prefecture_method FROM nearest
    """)
    counts = con.execute(f"""
        SELECT count(*) FILTER (WHERE prefecture_method = 'within'),
               count(*) FILTER (WHERE prefecture_method = 'nearest'),
               (SELECT count(*) FROM {points_table}) - count(*)
        FROM {points_table}_pref
    """).fetchone()
    return {
        "prefecture_within": counts[0],
        "prefecture_nearest": counts[1],
        "prefecture_none": counts[2],
    }
