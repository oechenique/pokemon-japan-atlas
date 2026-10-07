"""fuji_viewshed (día 5): la cuenca visual del Fuji como polígono simplificado.

El raster de raster_product (255 = visible) se vectoriza con rasterio, se une y se
simplifica a ~250 m (0,0025°), que alcanza para la escala del día. method guarda la
definición de "visible" para el texto del día.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from pipeline.transforms.base import create_table, data_root, gold_path, write_entity

PRODUCT = "fuji_viewshed"
SIMPLIFY_DEG = 0.0025
METHOD = (
    "Un punto ve el Fuji si ve la cumbre o algún punto del cono superior: 9 observadores "
    "(el punto más alto del DEM cerca de Kengamine y 8 a 1 km en todas las direcciones), "
    "observador y objetivo a 1,7 m, hasta 200 km, con curvatura y refracción (-cc 0,85714), "
    "sobre Copernicus DEM GLO-90 (90 m, de superficie: edificios y bosques tapan). "
    "Cálculo geométrico: no tiene en cuenta el clima ni la bruma."
)


def build(con: duckdb.DuckDBPyConnection, run_id: str, *, root: Path | None = None) -> dict:
    import rasterio
    from rasterio.features import shapes

    products = gold_path("raster_product", root).as_posix()
    rel, notice, license_ = con.execute(
        f"SELECT path, notice, license FROM read_parquet('{products}') WHERE product_id = ?",
        [PRODUCT],
    ).fetchone()
    raster = (root or data_root()) / "silver" / rel
    with rasterio.open(raster) as ds:
        visible = ds.read(1) == 255
        share = float(visible.mean())
        polygons = [
            json.dumps(geom)
            for geom, value in shapes(visible.astype("uint8"), mask=visible, transform=ds.transform)
            if value == 1
        ]
    create_table(con, "viewshed_parts", ("geojson",), [(p,) for p in polygons])
    query = f"""
        SELECT '{PRODUCT}' AS product_id, {share} AS visible_share,
               '{_quote(METHOD)}' AS method, '{_quote(notice)}' AS notice,
               '{_quote(license_)}' AS license,
               ST_SimplifyPreserveTopology(
                   ST_Union_Agg(ST_GeomFromGeoJSON(geojson)), {SIMPLIFY_DEG}) AS geometry
        FROM viewshed_parts
    """
    summary = write_entity(con, "fuji_viewshed", query, root=root, layer="gold")
    return {
        **summary,
        "stats": {"raster_polygons": len(polygons), "visible_share": round(share, 6)},
    }


def _quote(text: str) -> str:
    return text.replace("'", "''")
