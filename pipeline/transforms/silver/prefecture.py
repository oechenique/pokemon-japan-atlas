"""prefecture: las 47 prefecturas desde Natural Earth admin-1, con nombres de Wikidata.

- Geometría de Natural Earth, corregida con ST_MakeValid y llevada a MultiPolygon.
- Nombres ja/en/es de Wikidata (unidos por ISO 3166-2, JP-13), con Natural Earth como
  respaldo para ja/en.
- real_region de Natural Earth; si la deja vacía, del seed prefecture_regions.
- area_km2 sobre el elipsoide (ST_Area_Spheroid espera latitud, longitud).
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from pipeline.transforms.base import Bronze, create_table, sparql_rows, write_entity

NE_ADMIN1 = ("admin_1_states_provinces.zip", "ne_10m_admin_1_states_provinces.shp")
WIKIDATA_COLUMNS = ("prefecture", "iso", "name_ja", "name_en", "name_es")
LICENSE = "public-domain + CC0-1.0"


def build(con: duckdb.DuckDBPyConnection, bronze: Bronze, *, root: Path | None = None) -> dict:
    ne = bronze.zip_member("natural_earth", *NE_ADMIN1)
    rows = sparql_rows(bronze.json("wikidata", "prefectures.json"), WIKIDATA_COLUMNS)
    create_table(con, "wd_prefecture", WIKIDATA_COLUMNS, rows)
    regions = bronze.path("seeds", "prefecture_regions.csv")
    query = f"""
        WITH ne AS (
            SELECT iso_3166_2 AS prefecture_code, name_ja AS ne_name_ja, name AS ne_name_en,
                   region AS ne_region, wikidataid AS ne_wikidata,
                   ST_Multi(ST_MakeValid(geom)) AS geometry
            FROM ST_Read('{ne}')
            WHERE adm0_a3 = 'JPN'
        ),
        wd AS (
            SELECT iso, min(prefecture) AS qid, min(name_ja) AS name_ja,
                   min(name_en) AS name_en, min(name_es) AS name_es
            FROM wd_prefecture GROUP BY iso
        ),
        seed AS (SELECT * FROM read_csv('{regions}', all_varchar = true))
        SELECT ne.prefecture_code,
               coalesce(wd.name_ja, ne.ne_name_ja) AS name_ja,
               coalesce(wd.name_en, ne.ne_name_en) AS name_en,
               wd.name_es,
               coalesce(ne.ne_region, seed.real_region) AS real_region,
               CASE WHEN ne.ne_region IS NULL THEN 'seed' ELSE 'natural_earth' END
                   AS real_region_source,
               coalesce(wd.qid, ne.ne_wikidata) AS wikidata,
               ST_Area_Spheroid(ST_FlipCoordinates(ne.geometry)) / 1e6 AS area_km2,
               '{LICENSE}' AS license,
               ne.geometry
        FROM ne
        LEFT JOIN wd ON wd.iso = ne.prefecture_code
        LEFT JOIN seed USING (prefecture_code)
    """
    return write_entity(con, "prefecture", query, root=root)
