"""poi: puntos de OSM por categoría, deduplicados por id de OSM, más los Pokémon Café.

- Si un elemento aparece en más de una categoría, gana la primera de PRECEDENCE: las
  categorías Pokémon antes que las genéricas.
- Pokémon Center y Pokémon Store se separan por el nombre, no por la consulta: en OSM
  hay tiendas con el brand:wikidata de Pokémon Center y un Center con el brand de
  Store. Las reclasificaciones se cuentan (insumo del día 18).
- Pokémon Café: salen del seed pokemon_cafes (dirección oficial). El nodo de OSM que
  cada fila cita en coords_osm no se duplica.
- Nombres: name:ja o name para el japonés; name:en y name:es, sin inventar
  traducciones. plant_source solo en las centrales.
- Prefectura por ubicación (osm.assign_prefecture) y región del juego por prefectura.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from pipeline.transforms import osm
from pipeline.transforms.base import Bronze, silver_path, write_entity

PRECEDENCE = (
    "pokemon_center",
    "pokemon_store",
    "pokemon_cafe",
    "poke_lids",
    "onsen",
    "power_plant",
)
BY_NAME = (("pokemon_center", "^ポケモンセンター"), ("pokemon_store", "^ポケモンストア"))
OSM_LICENSE = "ODbL-1.0"
SEED_LICENSE = "LicenseRef-seeds + ODbL-1.0"


def build(con: duckdb.DuckDBPyConnection, bronze: Bronze, *, root: Path | None = None) -> dict:
    files = osm.overpass_files(bronze, "osm_overpass", PRECEDENCE)
    stats = osm.load_elements(con, "osm_poi", files, PRECEDENCE)
    stats["reclassified_by_name"] = reclassify_by_name(con, "osm_poi")
    cafes = bronze.path("seeds", "pokemon_cafes.csv")
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE poi_points AS
        WITH seed AS (SELECT * FROM read_csv('{cafes}', all_varchar = true)),
        from_osm AS (
            SELECT 'osm:' || osm_key AS poi_id, 'osm' AS source, osm_key AS source_id, category,
                   coalesce({osm.tag("name:ja")}, {osm.tag("name")}) AS name_ja,
                   {osm.tag("name:en")} AS name_en,
                   {osm.tag("name:es")} AS name_es,
                   CASE WHEN category = 'power_plant' THEN {osm.tag("plant:source")} END
                       AS plant_source,
                   NULL AS address_ja,
                   '{OSM_LICENSE}' AS license,
                   {osm.point_sql()} AS geometry
            FROM osm_poi
            WHERE 'osm:' || osm_key NOT IN (SELECT coords_osm FROM seed)
        ),
        from_seed AS (
            SELECT 'seed:' || cafe_id AS poi_id, 'seed' AS source, cafe_id AS source_id,
                   'pokemon_cafe' AS category, name_ja, name_en, NULL AS name_es,
                   NULL AS plant_source, address_ja, '{SEED_LICENSE}' AS license,
                   ST_SetCRS(ST_Point(lon::DOUBLE, lat::DOUBLE), 'OGC:CRS84') AS geometry
            FROM seed
        )
        SELECT * FROM from_osm UNION ALL SELECT * FROM from_seed
    """)
    stats["seed_cafes_replacing_osm"] = con.execute(
        f"SELECT count(*) FROM osm_poi WHERE 'osm:' || osm_key IN "
        f"(SELECT coords_osm FROM read_csv('{cafes}', all_varchar = true))"
    ).fetchone()[0]
    stats |= osm.assign_prefecture(con, "poi_points", "poi_id", root)
    regions = silver_path("game_region", root).as_posix()
    query = f"""
        WITH region_of AS (
            SELECT unnest(prefecture_codes) AS prefecture_code, region_id
            FROM read_parquet('{regions}')
        )
        SELECT p.poi_id, p.source, p.source_id, p.category, p.name_ja, p.name_en, p.name_es,
               p.plant_source, p.address_ja, pr.prefecture_code, pr.prefecture_method,
               r.region_id AS game_region,
               h3_latlng_to_cell_string(ST_Y(p.geometry), ST_X(p.geometry), 7) AS h3_r7,
               h3_latlng_to_cell_string(ST_Y(p.geometry), ST_X(p.geometry), 9) AS h3_r9,
               p.license, p.geometry
        FROM poi_points p
        LEFT JOIN poi_points_pref pr USING (poi_id)
        LEFT JOIN region_of r ON r.prefecture_code = pr.prefecture_code
    """
    summary = write_entity(con, "poi", query, root=root)
    return {**summary, "stats": stats}


def reclassify_by_name(con: duckdb.DuckDBPyConnection, table: str) -> int:
    """Corrige pokemon_center / pokemon_store según el nombre. Devuelve cuántos cambió."""
    name = f"coalesce({osm.tag('name:ja')}, {osm.tag('name')})"
    cases = " ".join(
        f"WHEN regexp_matches({name}, '{pattern}') THEN '{cat}'" for cat, pattern in BY_NAME
    )
    pokemon = ", ".join(f"'{cat}'" for cat, _ in BY_NAME)
    changed = con.execute(f"""
        SELECT count(*) FROM {table}
        WHERE category IN ({pokemon}) AND category <> CASE {cases} ELSE category END
    """).fetchone()[0]
    con.execute(f"""
        UPDATE {table} SET category = CASE {cases} ELSE category END
        WHERE category IN ({pokemon})
    """)
    return changed
