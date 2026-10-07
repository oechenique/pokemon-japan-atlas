"""Vistas gold.v_day_XX en data/gold/atlas.duckdb (reglas/03 y 04).

Cada vista lee los parquet de Gold por nombre relativo ('poi.parquet'), así la base no
depende de dónde esté el repo: hay que abrirla con open_atlas(), que fija
file_search_path en data/gold/.

Días sin vista (no tienen datos propios, reglas/04): 6 y 27 usan todas las capas, 7 sale
de cualquier vista, 10 trabaja sobre los artefactos publicados, 16 depende de los seeds
comunitarios (Fase 5) y 25 sale del manifest.json (Fase 3).
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from pipeline.transforms.base import GOLD, data_root

ATLAS_DB = "atlas.duckdb"
DAYS_WITHOUT_VIEW = (6, 7, 10, 16, 25, 27)
# Kyūshū (Hoenn) y sus mares, para el día 26: [oeste, sur, este, norte].
KYUSHU_WATERS = (127.5, 29.5, 133.0, 35.0)


def p(entity: str) -> str:
    return f"read_parquet('{entity}.parquet')"


VIEWS: dict[int, str] = {
    1: f"""SELECT poi_id, category, name_ja, name_en, name_es, prefecture_code, game_region,
                  geometry
           FROM {p("poi")} WHERE category IN ('pokemon_center', 'poke_lids')""",
    2: f"""SELECT rail_id, kind, kind = 'shinkansen' AS highlight, name_ja, name_en, operator,
                  length_m, geometry
           FROM {p("rail")}
           WHERE ST_Intersects(geometry,
                 (SELECT geometry FROM {p("game_region")} WHERE region_id = 'kanto'))""",
    3: f"""SELECT 'game_region' AS layer, region_id AS id, name_ja, name_en, name_es,
                  confidence, geometry FROM {p("game_region")}
           UNION ALL
           SELECT 'prefecture', prefecture_code, name_ja, name_en, name_es, NULL, geometry
           FROM {p("prefecture")}""",
    4: f"""SELECT cluster_id, layer, member_count, members, prefecture_codes, geometry
           FROM {p("poi_clusters")}""",
    5: f"""SELECT product_id, visible_share, method, notice, geometry FROM {p("fuji_viewshed")}""",
    8: f"""SELECT 'game_place' AS layer, place_id AS id, game_name, region_id, real_place,
                  confidence, source_url, geometry FROM {p("game_place")}
           UNION ALL
           SELECT 'game_region', region_id, game_name, region_id, real_region, confidence,
                  source_urls[1], geometry FROM {p("game_region")}""",
    9: f"""WITH region_of AS (SELECT unnest(prefecture_codes) AS prefecture_code, region_id
                              FROM {p("game_region")})
           SELECT h.h3, h.value AS population, h.prefecture_code, r.region_id AS game_region
           FROM {p("h3_metric")} h LEFT JOIN region_of r USING (prefecture_code)
           WHERE h.metric = 'population' AND h.resolution = 7""",
    11: f"""SELECT h3, value AS rings_from_track, is_proxy, prefecture_code FROM {p("h3_metric")}
            WHERE metric = 'shinkansen_sound_proxy'""",
    12: f"""SELECT * FROM {p("power_plants_kanto")}""",
    13: f"""SELECT * FROM {p("center_nearest_station")}""",
    14: f"""SELECT building_id, building, name, height_m, levels, geometry FROM {p("building")}""",
    15: f"""SELECT region_id, name_ja, name_en, name_es, real_region, geometry
            FROM {p("game_region")} WHERE region_id = 'sinnoh'""",
    17: f"""SELECT h3, value AS radiance, coverage, poor_quality_share, prefecture_code
            FROM {p("h3_metric")} WHERE metric = 'night_light' AND resolution = 7""",
    18: f"""SELECT 'finding' AS kind, finding_id AS id, title, value, total, share, source,
                   detail, NULL AS prefecture_code FROM {p("null_findings")}
            UNION ALL
            SELECT 'null_rate', entity || '.' || column_name, column_name, null_count, row_count,
                   rate, entity, NULL, prefecture_code FROM {p("null_rates_by_prefecture")}""",
    19: f"""SELECT poi_id, name_ja, name_en, prefecture_code, game_region,
                   game_region = 'hoenn' AS in_hoenn, geometry
            FROM {p("poi")} WHERE category = 'onsen'""",
    20: f"""SELECT h3, value AS pokemon_points, prefecture_code FROM {p("h3_metric")}
            WHERE metric = 'poi_density'""",
    21: f"""SELECT * FROM {p("osm_summary")}""",
    22: f"""SELECT prefecture_code, name_ja, name_en, name_es, real_region, area_km2, geometry
            FROM {p("prefecture")}""",
    23: f"""SELECT poi_id, name_ja, name_en, address_ja, prefecture_code, game_region, geometry
            FROM {p("poi")} WHERE category = 'pokemon_cafe'""",
    24: f"""SELECT 'station' AS layer, station_key AS id, name_ja AS name, kind,
                   array_to_string(lines, ' / ') AS detail, false AS schematic,
                   NULL::DOUBLE AS distance_km, geometry
            FROM {p("shinkansen_stations")}
            UNION ALL
            SELECT 'edge', edge_id, from_key || ' - ' || to_key, kind,
                   array_to_string(lines, ' / '), schematic, distance_km, geometry
            FROM {p("shinkansen_edges")}
            UNION ALL
            SELECT 'center_link', poi_id, center_name, NULL, station_name, false, distance_km,
                   geometry
            FROM {p("center_to_shinkansen")}""",
    26: f"""SELECT layer, feature_id, depth_m, geometry FROM {p("basemap")}
            WHERE layer IN ('bathymetry', 'coastline')
              AND ST_Intersects(geometry, ST_MakeEnvelope({", ".join(map(str, KYUSHU_WATERS))}))""",
    28: f"""SELECT region_id, game_name, generation, year, confidence, 'japan' AS where_, geometry
            FROM {p("game_region")}
            UNION ALL
            SELECT region_id, game_name, generation, year, confidence, 'outside', geometry
            FROM {p("outside_region")}""",
    29: f"""SELECT product_id, aoi, path, width, height, notice, geometry
            FROM {p("raster_product")} WHERE kind = 'hillshade'""",
    30: f"""SELECT 'game_region' AS layer, region_id AS id, name_en, geometry
            FROM {p("game_region")}
            UNION ALL
            SELECT 'prefecture', prefecture_code, name_en, geometry FROM {p("prefecture")}""",
}


def gold_dir(root: Path | None = None) -> Path:
    return (root or data_root()) / GOLD


def open_atlas(root: Path | None = None, *, read_only: bool = True) -> duckdb.DuckDBPyConnection:
    directory = gold_dir(root)
    con = duckdb.connect(str(directory / ATLAS_DB), read_only=read_only)
    con.load_extension("spatial")
    con.execute(f"SET file_search_path = '{directory.as_posix()}'")
    return con


def write_views(run_id: str, *, root: Path | None = None) -> dict:
    """Recrea atlas.duckdb con todas las vistas y verifica que cada una se pueda leer."""
    directory = gold_dir(root)
    target = directory / ATLAS_DB
    part = directory / (ATLAS_DB + ".part")
    part.unlink(missing_ok=True)
    con = duckdb.connect(str(part))
    try:
        con.load_extension("spatial")
        con.execute(f"SET file_search_path = '{directory.as_posix()}'")
        con.execute("CREATE SCHEMA gold")
        counts = {}
        for day, sql in sorted(VIEWS.items()):
            name = f"v_day_{day:02d}"
            con.execute(f"CREATE VIEW gold.{name} AS {sql}")
            counts[name] = con.execute(f"SELECT count(*) FROM gold.{name}").fetchone()[0]
        con.execute("CHECKPOINT")
    finally:
        con.close()
    part.replace(target)
    empty = sorted(name for name, n in counts.items() if n == 0)
    if empty:
        raise RuntimeError(f"vistas vacías: {empty}")
    return {"run_id": run_id, "views": counts, "days_without_view": list(DAYS_WITHOUT_VIEW)}
