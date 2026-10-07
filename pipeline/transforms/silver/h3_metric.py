"""h3_metric: métricas por celda H3 sobre tierra de Japón.

- population (Kontur, resolución 8 nativa y suma a 7).
- night_light (VIIRS Black Marble, resoluciones 8 y 7). Tratamiento de nulos:
  - un píxel cuenta si no es relleno y su calidad no es 255; la calidad 1 ("pobre")
    se incluye y su fracción va en poor_quality_share;
  - solo píxeles sobre tierra de Japón: los que caen en una prefectura, más las celdas
    pobladas de Kontur que quedan fuera de las prefecturas (islas chicas como
    Ogasawara, que Natural Earth a 10 m no tiene);
  - value es el promedio de los píxeles válidos y coverage, su fracción;
  - sin ningún píxel válido, value es NULL, nunca 0 (por ejemplo, Chichijima).
- poi_density: cantidad de puntos Pokémon (Center, Store, Café y Poké Lids) por celda
  de resolución 7.
- shinkansen_sound_proxy (día 11): celdas de resolución 9 a 2 anillos o menos (unos
  500 m) de un vértice de una vía del Shinkansen. value es la distancia en anillos (0
  a 2). Es un proxy declarado (is_proxy), no una medición de ruido.

prefecture_code de cada celda: la prefectura que contiene su centro.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import numpy as np

from pipeline.transforms.base import Bronze, silver_path, write_entity

POKEMON_CATEGORIES = ("pokemon_center", "pokemon_store", "pokemon_cafe", "poke_lids")
NIGHT_LAYER = "AllAngle_Composite_Snow_Free"
QUALITY_FILL = 255
SOUND_RING = 2


def build(con: duckdb.DuckDBPyConnection, bronze: Bronze, *, root: Path | None = None) -> dict:
    stats = {}
    kontur = bronze.path("kontur_population", "population_jp_20231101.gpkg.gz")
    stats |= _night_light(con, bronze, kontur, root)
    poi = silver_path("poi", root).as_posix()
    rail = silver_path("rail", root).as_posix()
    prefecture = silver_path("prefecture", root).as_posix()
    pokemon = ", ".join(f"'{c}'" for c in POKEMON_CATEGORIES)
    query = f"""
        WITH population_r8 AS (
            SELECT h3, 8 AS resolution, 'population' AS metric, population::DOUBLE AS value,
                   NULL::DOUBLE AS coverage, NULL::DOUBLE AS poor_quality_share,
                   false AS is_proxy, 'kontur_population' AS source, 'CC-BY-4.0' AS license
            FROM ST_Read('/vsigzip/{kontur}')
        ),
        population_r7 AS (
            SELECT h3_cell_to_parent(h3, 7) AS h3, 7 AS resolution, 'population' AS metric,
                   sum(value) AS value, NULL::DOUBLE, NULL::DOUBLE, false, 'kontur_population',
                   'CC-BY-4.0'
            FROM population_r8 GROUP BY 1
        ),
        poi_density AS (
            SELECT h3_r7 AS h3, 7, 'poi_density', count(*)::DOUBLE, NULL::DOUBLE, NULL::DOUBLE,
                   false, 'osm_overpass', 'ODbL-1.0'
            FROM read_parquet('{poi}') WHERE category IN ({pokemon}) GROUP BY 1
        ),
        vertices AS (
            SELECT DISTINCT h3_latlng_to_cell_string(ST_Y(d.geom), ST_X(d.geom), 9) AS origin
            FROM (SELECT unnest(ST_Dump(ST_Points(geometry))) AS d
                  FROM read_parquet('{rail}') WHERE kind = 'shinkansen')
        ),
        rings AS (
            SELECT unnest(h3_grid_disk(origin, {SOUND_RING})) AS neighbor, origin FROM vertices
        ),
        sound AS (
            SELECT neighbor AS h3, 9, 'shinkansen_sound_proxy',
                   min(h3_grid_distance(neighbor, origin))::DOUBLE,
                   NULL::DOUBLE, NULL::DOUBLE, true, 'osm_overpass', 'ODbL-1.0'
            FROM rings GROUP BY 1
        ),
        metrics AS (
            SELECT * FROM population_r8
            UNION ALL SELECT * FROM population_r7
            UNION ALL SELECT * FROM night_light
            UNION ALL SELECT * FROM poi_density
            UNION ALL SELECT * FROM sound
        ),
        centers AS (
            SELECT DISTINCT h3,
                   ST_SetCRS(ST_Point(h3_cell_to_lng(h3), h3_cell_to_lat(h3)), 'OGC:CRS84') AS pt
            FROM metrics
        ),
        cell_prefecture AS (
            SELECT c.h3, min(p.prefecture_code) AS prefecture_code
            FROM centers c JOIN read_parquet('{prefecture}') p ON ST_Within(c.pt, p.geometry)
            GROUP BY c.h3
        )
        SELECT m.h3, m.resolution, m.metric, m.value, m.coverage, m.poor_quality_share,
               cp.prefecture_code, m.is_proxy, m.source, m.license
        FROM metrics m LEFT JOIN cell_prefecture cp USING (h3)
    """
    summary = write_entity(con, "h3_metric", query, root=root)
    return {**summary, "stats": stats}


def _night_light(
    con: duckdb.DuckDBPyConnection, bronze: Bronze, kontur: str, root: Path | None
) -> dict:
    """Crea la tabla temporal night_light (resoluciones 8 y 7) desde los píxeles."""
    import pyarrow as pa
    import rasterio
    from rasterio.features import rasterize

    radiance_path = bronze.path("viirs_night", f"{NIGHT_LAYER}.tif")
    quality_path = bronze.path("viirs_night", f"{NIGHT_LAYER}_Quality.tif")
    prefecture = silver_path("prefecture", root).as_posix()
    shapes = [
        (json.loads(g), 1)
        for (g,) in con.execute(
            f"SELECT ST_AsGeoJSON(geometry) FROM read_parquet('{prefecture}')"
        ).fetchall()
    ]
    # Celdas pobladas fuera de las prefecturas: si vive gente, es tierra.
    extra = con.execute(f"""
        WITH cells AS (
            SELECT h3, ST_Point(h3_cell_to_lng(h3), h3_cell_to_lat(h3)) AS pt
            FROM ST_Read('/vsigzip/{kontur}')
        )
        SELECT ST_AsGeoJSON(ST_GeomFromText(h3_cell_to_boundary_wkt(c.h3)))
        FROM cells c
        WHERE NOT EXISTS (
            SELECT 1 FROM read_parquet('{prefecture}') p
            WHERE ST_Within(ST_SetCRS(c.pt, 'OGC:CRS84'), p.geometry)
        )
    """).fetchall()
    shapes += [(json.loads(g), 1) for (g,) in extra]
    with rasterio.open(radiance_path) as rad, rasterio.open(quality_path) as qual:
        radiance = rad.read(1)
        quality = qual.read(1)
        land = rasterize(
            shapes, out_shape=rad.shape, transform=rad.transform, fill=0, dtype="uint8"
        )
        rows, cols = np.nonzero(land)
        lon = rad.transform.c + rad.transform.a * (cols + 0.5)
        lat = rad.transform.f + rad.transform.e * (rows + 0.5)
        value = radiance[rows, cols].astype("float64")
        flag = quality[rows, cols]
        valid = (value != rad.nodata) & (flag != QUALITY_FILL) & np.isfinite(value)
    table = pa.table(
        {
            "lat": lat,
            "lon": lon,
            "value": pa.array(np.where(valid, value, 0.0), mask=~valid),
            "poor": pa.array((flag == 1) & valid),
        }
    )
    con.register("viirs_pixels", table)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE night_light AS
        WITH px AS (
            SELECT h3_latlng_to_cell_string(lat, lon, 8) AS r8, value, poor FROM viirs_pixels
        ),
        cells AS (
            SELECT r8 AS h3, 8 AS resolution, value, poor FROM px
            UNION ALL
            SELECT h3_cell_to_parent(r8, 7), 7, value, poor FROM px
        )
        SELECT h3, resolution, 'night_light' AS metric,
               avg(value) AS value,
               count(value) / count(*) AS coverage,
               CASE WHEN count(value) > 0
                    THEN count(*) FILTER (WHERE poor) / count(value) END AS poor_quality_share,
               false AS is_proxy, 'viirs_night' AS source, 'CC0-1.0' AS license
        FROM cells GROUP BY h3, resolution
    """)
    con.unregister("viirs_pixels")
    counts = con.execute("""
        SELECT count(*) FILTER (WHERE resolution = 8),
               count(*) FILTER (WHERE resolution = 8 AND value IS NULL)
        FROM night_light
    """).fetchone()
    return {
        "night_light_extra_land_cells": len(extra),
        "night_light_land_pixels": int(land.sum()),
        "night_light_valid_pixels": int(valid.sum()),
        "night_light_cells_r8": counts[0],
        "night_light_cells_r8_null": counts[1],
    }
