"""Utilidades de rasters de Silver: COG, relieve sombreado y cuenca visual.

- Los rasters de Silver son COG en EPSG:4326, con compresión deflate. GDAL escribe el
  mismo archivo byte a byte si la entrada no cambia.
- La cuenca visual usa gdal_viewshed (gdal-bin de Debian) por subprocess, separado de
  rasterio, sobre el DEM reproyectado a UTM: gdal_viewshed mide distancias en las
  unidades del CRS, así que no sirve con grados.
"""

from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from pipeline.transforms.base import TransformError

COG_OPTIONS = {
    "driver": "COG",
    "compress": "DEFLATE",
    "blocksize": 512,
    "overview_resampling": "nearest",
}
# Metros por grado de latitud (WGS84, valor medio) para pasar la grilla a metros.
METERS_PER_DEGREE = 111_320.0
HILLSHADE_NODATA = 0


def to_cog(src: Path | str, dst: Path, *, predictor: int = 2) -> None:
    import rasterio.shutil

    part = dst.with_name(dst.name + ".part")
    part.unlink(missing_ok=True)
    rasterio.shutil.copy(str(src), str(part), predictor=predictor, **COG_OPTIONS)
    part.replace(dst)


def hillshade(
    dem: np.ndarray,
    *,
    res_x_deg: float,
    res_y_deg: float,
    lat_center: np.ndarray,
    nodata: float | None,
    azimuth: float = 315.0,
    altitude: float = 45.0,
) -> np.ndarray:
    """Relieve sombreado clásico (Horn) sobre una grilla en grados.

    El tamaño de píxel en metros se calcula por fila (cos de la latitud), así que vale
    para todo Japón. Devuelve uint8 de 1 a 255; 0 es sin dato.
    """
    z = dem.astype("float64")
    invalid = ~np.isfinite(z) if nodata is None else (z == nodata) | ~np.isfinite(z)
    z = np.where(invalid, np.nan, z)
    padded = np.pad(z, 1, mode="edge")
    dx_m = res_x_deg * METERS_PER_DEGREE * np.cos(np.radians(lat_center))[:, None]
    dy_m = res_y_deg * METERS_PER_DEGREE
    a, b, c = padded[:-2, :-2], padded[:-2, 1:-1], padded[:-2, 2:]
    d, f = padded[1:-1, :-2], padded[1:-1, 2:]
    g, h, i = padded[2:, :-2], padded[2:, 1:-1], padded[2:, 2:]
    dzdx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8 * dx_m)
    dzdy = ((g + 2 * h + i) - (a + 2 * b + c)) / (8 * dy_m)
    slope = np.arctan(np.hypot(dzdx, dzdy))
    aspect = np.arctan2(dzdy, -dzdx)
    zenith = math.radians(90.0 - altitude)
    az = math.radians(360.0 - azimuth + 90.0)
    shade = np.cos(zenith) * np.cos(slope) + np.sin(zenith) * np.sin(slope) * np.cos(az - aspect)
    out = np.clip(np.round(1 + 254 * np.clip(shade, 0, 1)), 1, 255)
    out = np.where(np.isnan(shade) | invalid, HILLSHADE_NODATA, out)
    return out.astype("uint8")


def gdal_viewshed_binary() -> str:
    path = shutil.which("gdal_viewshed")
    if path is None:
        raise TransformError("falta gdal_viewshed (gdal-bin) en la imagen")
    return path


def viewshed(
    dem: Path,
    dst: Path,
    *,
    lon: float,
    lat: float,
    max_distance_m: float,
    observer_height_m: float,
    target_height_m: float,
    utm_epsg: int,
    resolution_m: float,
    summit_search_m: float = 500.0,
    ring_radius_m: float = 0.0,
    ring_points: int = 0,
) -> dict[str, float]:
    """Cuenca visual en EPSG:4326 (255 = visible, 0 = no visible) desde (lon, lat).

    1. Reproyecta el DEM a UTM con la resolución pedida (bilinear).
    2. Pone el observador central en el punto más alto del DEM a menos de
       summit_search_m del punto pedido: con píxeles de 90 m, la coordenada de una
       cumbre puede caer dentro de un cráter.
    3. Con ring_points > 0 suma observadores a ring_radius_m del central, repartidos
       en todas las direcciones. Un punto ve la montaña si ve cualquiera de ellos: desde
       la meseta de una cumbre, el borde vecino tapa las vistas que bajan por la ladera.
    4. Corre gdal_viewshed por observador, con curvatura y refracción (-cc 0.85714), y
       une los resultados.
    5. Vuelve el resultado a EPSG:4326 sobre la grilla del DEM original (nearest).
    """
    import rasterio
    from rasterio.warp import Resampling, calculate_default_transform, reproject, transform

    with tempfile.TemporaryDirectory(prefix="viewshed-") as tmp:
        utm_dem = Path(tmp) / "dem_utm.tif"
        with rasterio.open(dem) as src:
            dst_crs = f"EPSG:{utm_epsg}"
            tr, width, height = calculate_default_transform(
                src.crs, dst_crs, src.width, src.height, *src.bounds, resolution=resolution_m
            )
            profile = {
                "driver": "GTiff",
                "dtype": "float32",
                "count": 1,
                "width": width,
                "height": height,
                "crs": dst_crs,
                "transform": tr,
                "nodata": src.nodata,
                "compress": "deflate",
                "tiled": True,
            }
            with rasterio.open(utm_dem, "w", **profile) as out:
                reproject(
                    rasterio.band(src, 1),
                    rasterio.band(out, 1),
                    resampling=Resampling.bilinear,
                    src_nodata=src.nodata,
                    dst_nodata=src.nodata,
                )
            grid = {
                "crs": src.crs,
                "transform": src.transform,
                "width": src.width,
                "height": src.height,
            }
        xs, ys = transform("EPSG:4326", f"EPSG:{utm_epsg}", [lon], [lat])
        x, y, elevation = highest_point(utm_dem, xs[0], ys[0], summit_search_m)
        observers = [(x, y)] + [
            (
                x + ring_radius_m * math.sin(2 * math.pi * k / ring_points),
                y + ring_radius_m * math.cos(2 * math.pi * k / ring_points),
            )
            for k in range(ring_points)
        ]
        # Cada salida de gdal_viewshed se recorta al radio de su observador: se lleva a
        # la grilla final (EPSG:4326, la del DEM original) y ahí se unen.
        union = np.zeros((grid["height"], grid["width"]), dtype=bool)
        for index, (ox, oy) in enumerate(observers):
            single = Path(tmp) / f"viewshed_{index}.tif"
            run_viewshed(
                utm_dem,
                single,
                x=ox,
                y=oy,
                max_distance_m=max_distance_m,
                observer_height_m=observer_height_m,
                target_height_m=target_height_m,
            )
            on_grid = np.zeros_like(union, dtype="uint8")
            with rasterio.open(single) as ds:
                reproject(
                    rasterio.band(ds, 1),
                    on_grid,
                    dst_transform=grid["transform"],
                    dst_crs=grid["crs"],
                    resampling=Resampling.nearest,
                )
            union |= on_grid == 255
        part = dst.with_name(dst.name + ".tmp.tif")
        profile = {
            "driver": "GTiff",
            "dtype": "uint8",
            "count": 1,
            "width": grid["width"],
            "height": grid["height"],
            "crs": grid["crs"],
            "transform": grid["transform"],
            "nodata": None,
            "compress": "deflate",
            "tiled": True,
        }
        with rasterio.open(part, "w", **profile) as out:
            out.write(np.where(union, 255, 0).astype("uint8"), 1)
        to_cog(part, dst)
        part.unlink()
    import rasterio as rio

    with rio.open(dst) as ds:
        data = ds.read(1)
    back = transform(f"EPSG:{utm_epsg}", "EPSG:4326", [x], [y])
    return {
        "visible_share": float((data == 255).mean()),
        "observer_lon": round(back[0][0], 6),
        "observer_lat": round(back[1][0], 6),
        "observer_elevation_m": round(elevation, 1),
        "observers": len(observers),
    }


def highest_point(dem: Path, x: float, y: float, radius_m: float) -> tuple[float, float, float]:
    """Centro del píxel más alto a menos de radius_m de (x, y), en las unidades del DEM."""
    import rasterio
    from rasterio.windows import from_bounds

    with rasterio.open(dem) as ds:
        window = from_bounds(x - radius_m, y - radius_m, x + radius_m, y + radius_m, ds.transform)
        window = window.round_offsets().round_lengths()
        data = ds.read(1, window=window, masked=True)
        tr = ds.window_transform(window)
    rows, cols = np.indices(data.shape)
    px = tr.c + tr.a * (cols + 0.5)
    py = tr.f + tr.e * (rows + 0.5)
    inside = (px - x) ** 2 + (py - y) ** 2 <= radius_m**2
    candidates = np.ma.masked_where(~inside, data)
    r, c = np.unravel_index(np.ma.argmax(candidates), data.shape)
    return float(px[r, c]), float(py[r, c]), float(data[r, c])


def run_viewshed(
    dem: Path,
    dst: Path,
    *,
    x: float,
    y: float,
    max_distance_m: float,
    observer_height_m: float,
    target_height_m: float,
) -> None:
    """gdal_viewshed sobre un DEM en metros. Separado para poder probarlo solo."""
    command = [
        gdal_viewshed_binary(),
        "-ox",
        repr(x),
        "-oy",
        repr(y),
        "-oz",
        repr(observer_height_m),
        "-tz",
        repr(target_height_m),
        "-md",
        repr(max_distance_m),
        "-cc",
        "0.85714",
        "-vv",
        "255",
        "-iv",
        "0",
        "-ov",
        "0",
        "-f",
        "GTiff",
        "-co",
        "COMPRESS=DEFLATE",
        str(dem),
        str(dst),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0 or not dst.is_file():
        raise TransformError(f"gdal_viewshed falló ({result.returncode}): {result.stderr[-500:]}")


def footprint_wkt(bounds: Sequence[float]) -> str:
    west, south, east, north = bounds
    return (
        f"POLYGON(({west} {south}, {east} {south}, {east} {north}, {west} {north}, {west} {south}))"
    )
