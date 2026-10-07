"""raster_product: rasters derivados del DEM GLO-90, como COG en data/silver/rasters/.

- dem: cada recorte de Bronze convertido a COG.
- hillshade: relieve sombreado de las 4 regiones del juego (día 29).
- viewshed: desde dónde se ve el Fuji (día 5). Por reciprocidad, se calcula desde la
  cumbre con el observador y el objetivo a 1,7 m: es lo que ve una persona parada en
  cada punto mirando la montaña. "Se ve el Fuji" = se ve la cumbre o algún punto del
  cono superior: 9 observadores (el punto más alto cerca de Kengamine y 8 a 1 km).
  Con uno solo, la meseta de la cumbre tapaba vistas clásicas como la del lago
  Kawaguchi. Hasta 200 km, con curvatura y
  refracción. Es un DSM: edificios y bosques tapan, como en la realidad.

Cada fila lleva el aviso de Copernicus GLO-90 (art. 6, ver NOTICE).
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np

from pipeline.sources.base import sha256_file
from pipeline.transforms import rasters
from pipeline.transforms.base import Bronze, create_table, data_root, write_entity

RASTERS_DIR = "rasters"
HILLSHADE_AOIS = ("kanto", "kansai", "kyushu", "hokkaido")
FUJI = {"lon": 138.7274, "lat": 35.3606}
VIEWSHED = {
    "aoi": "fuji_viewshed",
    "max_distance_m": 200_000,
    "observer_height_m": 1.7,
    "target_height_m": 1.7,
    # UTM 54N cubre los 138-144° E; el Fuji está en 138,7° E.
    "utm_epsg": 32654,
    "resolution_m": 90,
    # "Se ve el Fuji" = se ve la cumbre o algún punto del cono superior: observadores
    # en la cumbre y a 1 km en 8 direcciones (unos 3400 m de altura).
    "ring_radius_m": 1000,
    "ring_points": 8,
}
LICENSE = "LicenseRef-Copernicus-WorldDEM-90"


def build(con: duckdb.DuckDBPyConnection, bronze: Bronze, *, root: Path | None = None) -> dict:
    import rasterio

    params = _dem_params(bronze)
    notice = bronze.metadata("copernicus_dem")["attribution"]
    out_dir = (root or data_root()) / "silver" / RASTERS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []

    for aoi in params["aois"]:
        src = Path(bronze.path("copernicus_dem", f"{aoi}.tif"))
        dst = out_dir / f"{aoi}_dem.tif"
        rasters.to_cog(src, dst, predictor=3)
        rows.append(_row(f"{aoi}_dem", "dem", aoi, dst, notice))

    for aoi in HILLSHADE_AOIS:
        src = Path(bronze.path("copernicus_dem", f"{aoi}.tif"))
        dst = out_dir / f"{aoi}_hillshade.tif"
        with rasterio.open(src) as ds:
            dem = ds.read(1)
            rows_lat = ds.transform.f + ds.transform.e * (np.arange(ds.height) + 0.5)
            shade = rasters.hillshade(
                dem,
                res_x_deg=ds.transform.a,
                res_y_deg=-ds.transform.e,
                lat_center=rows_lat,
                nodata=ds.nodata,
            )
            profile = {**ds.profile, "dtype": "uint8", "nodata": rasters.HILLSHADE_NODATA}
        part = dst.with_name(dst.name + ".tmp.tif")
        with rasterio.open(part, "w", **{**profile, "driver": "GTiff"}) as out:
            out.write(shade, 1)
        rasters.to_cog(part, dst)
        part.unlink()
        rows.append(_row(f"{aoi}_hillshade", "hillshade", aoi, dst, notice))

    src = Path(bronze.path("copernicus_dem", f"{VIEWSHED['aoi']}.tif"))
    dst = out_dir / "fuji_viewshed.tif"
    stats = rasters.viewshed(
        src,
        dst,
        lon=FUJI["lon"],
        lat=FUJI["lat"],
        **{k: v for k, v in VIEWSHED.items() if k != "aoi"},
    )
    rows.append(_row("fuji_viewshed", "viewshed", VIEWSHED["aoi"], dst, notice))

    columns = ("product_id", "kind", "aoi", "path", "width", "height", "sha256", "notice", "wkt")
    create_table(con, "raster_rows", columns, rows)
    query = f"""
        SELECT product_id, kind, aoi, path, width, height, sha256, notice,
               '{LICENSE}' AS license, ST_GeomFromText(wkt) AS geometry
        FROM raster_rows
    """
    summary = write_entity(con, "raster_product", query, root=root)
    return {
        **summary,
        "stats": {
            "fuji_" + k: (round(v, 6) if k == "visible_share" else v) for k, v in stats.items()
        },
    }


def _dem_params(bronze: Bronze) -> dict:
    from pipeline.sources.registry import load_registry

    return load_registry().get("copernicus_dem").params


def _row(product_id: str, kind: str, aoi: str, path: Path, notice: str) -> tuple:
    import rasterio

    with rasterio.open(path) as ds:
        width, height = ds.width, ds.height
        b = ds.bounds
    wkt = rasters.footprint_wkt((b.left, b.bottom, b.right, b.top))
    rel = f"{RASTERS_DIR}/{path.name}"
    return (product_id, kind, aoi, rel, width, height, sha256_file(path), notice, wkt)
