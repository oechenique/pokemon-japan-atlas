"""basemap: mapa base global desde Natural Earth 10m (dominio público).

Capas: land, ocean, coastline, country, urban_area, populated_place y bathymetry (los
12 niveles de profundidad). Es global porque lo usa el globo antes de llegar a Japón.

- feature_id: el NE_ID cuando la capa lo tiene (países y ciudades); si no, la capa y el
  orden de la fila en el archivo, que es estable.
- Las geometrías pasan por ST_MakeValid y se quedan con la dimensión de su capa
  (polígonos, líneas o puntos), para que no aparezcan colecciones mezcladas.
- Se excluye "Null island", el elemento ficticio que Natural Earth pone en 0°, 0° en
  las capas de costas y tierra (featurecla = 'Null island', scalerank 100). Se cuenta
  en las estadísticas.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import duckdb

from pipeline.transforms.base import Bronze, write_entity

LICENSE = "public-domain"
# capa -> (zip de Bronze, shapefile, dimensión: 1 punto, 2 línea, 3 polígono)
LAYERS = {
    "land": ("land.zip", "ne_10m_land.shp", 3),
    "ocean": ("ocean.zip", "ne_10m_ocean.shp", 3),
    "coastline": ("coastline.zip", "ne_10m_coastline.shp", 2),
    "country": ("admin_0_countries.zip", "ne_10m_admin_0_countries.shp", 3),
    "urban_area": ("urban_areas.zip", "ne_10m_urban_areas.shp", 3),
    "populated_place": ("populated_places.zip", "ne_10m_populated_places.shp", 1),
}
BATHYMETRY_ZIP = "bathymetry_all.zip"
NULL_ISLAND = "Null island"


def build(con: duckdb.DuckDBPyConnection, bronze: Bronze, *, root: Path | None = None) -> dict:
    parts = []
    for layer, (archive, shp, dimension) in LAYERS.items():
        path = bronze.zip_member("natural_earth", archive, shp)
        named = layer in ("country", "populated_place")
        feature_id = "'ne:' || NE_ID::BIGINT" if named else f"'{layer}:' || row_number() OVER ()"
        parts.append(f"""
            SELECT '{layer}' AS layer,
                   {feature_id} AS feature_id,
                   {"NAME_EN" if named else "NULL"} AS name_en,
                   {"NAME_ES" if named else "NULL"} AS name_es,
                   {"NAME_JA" if named else "NULL"} AS name_ja,
                   NULL AS depth_m,
                   {"SCALERANK" if layer == "populated_place" else "scalerank"} AS scalerank,
                   {_geometry("geom", dimension)} AS geometry
            FROM ST_Read('{path}')
            WHERE {_not_null_island(con, path)}
        """)
    null_island = sum(
        con.execute(
            f"SELECT count(*) FROM ST_Read('{bronze.zip_member('natural_earth', a, s)}') "
            f"WHERE {_is_null_island(con, bronze.zip_member('natural_earth', a, s))}"
        ).fetchone()[0]
        for a, s, _ in LAYERS.values()
    )
    bathymetry = Path(bronze.path("natural_earth", BATHYMETRY_ZIP))
    with zipfile.ZipFile(bathymetry) as zf:
        members = sorted(n for n in zf.namelist() if n.endswith(".shp"))
    for member in members:
        path = bronze.zip_member("natural_earth", BATHYMETRY_ZIP, member)
        parts.append(f"""
            SELECT 'bathymetry' AS layer,
                   'bathymetry:' || depth::INTEGER || ':' || row_number() OVER () AS feature_id,
                   NULL, NULL, NULL, depth::INTEGER AS depth_m, scalerank,
                   {_geometry("geom", 3)} AS geometry
            FROM ST_Read('{path}')
        """)
    query = f"""
        SELECT layer, feature_id, name_en, name_es, name_ja, depth_m, scalerank,
               '{LICENSE}' AS license, geometry
        FROM ({" UNION ALL ".join(parts)})
        WHERE geometry IS NOT NULL AND NOT ST_IsEmpty(geometry)
    """
    summary = write_entity(con, "basemap", query, root=root)
    return {
        **summary,
        "stats": {"bathymetry_levels": len(members), "null_island_excluded": null_island},
    }


def _geometry(column: str, dimension: int) -> str:
    if dimension == 1:
        return column
    return f"ST_CollectionExtract(ST_MakeValid({column}), {dimension})"


def _featurecla(con: duckdb.DuckDBPyConnection, path: str) -> str | None:
    """Nombre de la columna featurecla (cambia de mayúsculas según la capa), si existe."""
    columns = con.execute(f"DESCRIBE SELECT * FROM ST_Read('{path}') LIMIT 0").fetchall()
    return next((c[0] for c in columns if c[0].lower() == "featurecla"), None)


def _is_null_island(con: duckdb.DuckDBPyConnection, path: str) -> str:
    column = _featurecla(con, path)
    return "false" if column is None else f"{column} = '{NULL_ISLAND}'"


def _not_null_island(con: duckdb.DuckDBPyConnection, path: str) -> str:
    column = _featurecla(con, path)
    return "true" if column is None else f"coalesce({column}, '') <> '{NULL_ISLAND}'"
