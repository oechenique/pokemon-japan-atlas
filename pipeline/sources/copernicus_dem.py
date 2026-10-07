"""copernicus_dem: recortes del Copernicus DEM GLO-90 para cada AOI del registro.

Nunca se baja el DEM global (reglas/03): se leen solo las teselas COG de 1° que tocan
cada AOI, vía /vsis3/ sin credenciales, y se guarda el recorte como GeoTIFF.

Idempotencia: la firma de un recorte es su bbox más el ETag de cada tesela. Si
coincide con la de la corrida anterior, el recorte se reusa sin leer el bucket.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from pipeline.sources.base import BronzeRun, IngestError, sha256_json

NODATA = -32767.0
GDAL_OPTIONS = {
    "AWS_NO_SIGN_REQUEST": "YES",
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
    "GDAL_HTTP_MAX_RETRY": "5",
    "GDAL_HTTP_RETRY_DELAY": "2",
}


def ingest(run: BronzeRun) -> None:
    params = run.source.params
    bucket, region = params["bucket"], params["region"]
    base_url = f"https://{bucket}.s3.{region}.amazonaws.com"
    run.download("tileList.txt", f"{base_url}/tileList.txt")
    available = set(run.path("tileList.txt").read_text(encoding="utf-8").split())

    for aoi, bbox in params["aois"].items():
        rel = f"{aoi}.tif"
        if run.done(rel):
            continue
        tiles = [t for t in tiles_for_bbox(bbox, params["tile_name"]) if t in available]
        if not tiles:
            raise IngestError(f"{aoi}: ninguna tesela del DEM toca el bbox {bbox}")
        etags = {}
        for tile in tiles:
            response = run.session.head(f"{base_url}/{tile}/{tile}.tif", timeout=60)
            response.raise_for_status()
            etags[tile] = response.headers["ETag"]
        signature = sha256_json({"bbox": bbox, "tiles": etags, "nodata": NODATA})
        extra = {"bbox": bbox, "tiles": len(tiles), "signature": signature}
        previous = run.previous_record(rel)
        if previous is not None and previous.extra.get("signature") == signature:
            run.reuse(rel, url=f"s3://{bucket}", extra=extra)
            continue
        _crop(run, rel, [f"/vsis3/{bucket}/{t}/{t}.tif" for t in tiles], bbox, region)
        run.commit(rel, run.part_path(rel), url=f"s3://{bucket}", extra=extra)


def tiles_for_bbox(bbox: Sequence[float], template: str) -> list[str]:
    """Nombres de las teselas de 1° que tocan [sur, oeste, norte, este]."""
    south, west, north, east = bbox
    names = []
    for lat in range(math.floor(south), math.ceil(north)):
        for lon in range(math.floor(west), math.ceil(east)):
            names.append(template.format(lat=_hemi(lat, "N", "S", 2), lon=_hemi(lon, "E", "W", 3)))
    return names


def _hemi(value: int, positive: str, negative: str, width: int) -> str:
    return f"{positive if value >= 0 else negative}{abs(value):0{width}d}"


def _crop(run: BronzeRun, rel: str, paths: list[str], bbox: Sequence[float], region: str) -> None:
    import rasterio
    from rasterio.merge import merge

    south, west, north, east = bbox
    with rasterio.Env(
        AWS_REGION=region, GDAL_HTTP_USERAGENT=run.registry.user_agent, **GDAL_OPTIONS
    ):
        datasets = [rasterio.open(path) for path in paths]
        try:
            mosaic, transform = merge(
                datasets, bounds=(west, south, east, north), nodata=NODATA, dtype="float32"
            )
            crs = datasets[0].crs
        finally:
            for dataset in datasets:
                dataset.close()
    profile = {
        "driver": "GTiff",
        "dtype": "float32",
        "count": 1,
        "width": mosaic.shape[2],
        "height": mosaic.shape[1],
        "crs": crs,
        "transform": transform,
        "nodata": NODATA,
        "compress": "deflate",
        "predictor": 3,
        "tiled": True,
        "blockxsize": 512,
        "blockysize": 512,
    }
    with rasterio.open(run.part_path(rel), "w", **profile) as out:
        out.write(mosaic)
        out.update_tags(source="Copernicus DEM GLO-90", notice=run.source.attribution)
