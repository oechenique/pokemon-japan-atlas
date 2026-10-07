"""viirs_night: NASA Black Marble VNP46A4 (CC0), recortado a Japón.

Se bajan solo las teselas HDF5 de 10° del registro, de a una, a un directorio
temporal; se pegan en un mosaico con la extensión de crop_bbox y se descartan
(reglas/03: se guarda el recorte, no la tesela). Queda una GeoTIFF por capa.

- Idempotencia: la firma del recorte es el nombre, tamaño y mtime de cada tesela en
  el listado de LAADS, más las capas y el bbox. Si coincide con la de la corrida
  anterior, se reusa el recorte sin bajar nada.
- Token: EARTHDATA_TOKEN (token de usuario de Earthdata Login, vence a los 60 días).
  Si falta o venció, se reusa el recorte de la corrida anterior y se avisa en
  metadata.json. Sin corrida anterior, la ingesta falla.
"""

from __future__ import annotations

import base64
import json
import os
import re
import tempfile
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from pipeline.sources.base import CHUNK, BronzeRun, IngestError, sha256_json, write_stream

GRID_PATH = "HDFEOS/GRIDS/VIIRS_Grid_DNB_2d/Data Fields"
# 15 segundos de arco: 240 píxeles por grado, 2400 por tesela de 10°.
PIXELS_PER_DEGREE = 240
TILE_DEGREES = 10
TOKEN_WARNING_DAYS = 14


class AuthError(IngestError):
    """Earthdata rechazó el token (falta, venció o no autoriza LAADS)."""


def ingest(run: BronzeRun) -> None:
    params = run.source.params
    archive = params["archive_url"].format(year=params["year"])
    listing_rel = "listing.json"
    _save_listing(run, listing_rel, archive.rstrip("/") + ".json")
    tiles = select_tiles(
        run.read_json(listing_rel), params["product"], params["year"], params["tiles"]
    )

    signature = sha256_json(
        {
            "tiles": [[t["name"], t["size"], t["mtime"]] for t in tiles],
            "layers": params["layers"],
            "crop_bbox": params["crop_bbox"],
        }
    )
    extra = {"tiles": [t["name"] for t in tiles], "signature": signature}
    rels = [f"{layer}.tif" for layer in params["layers"]]
    run.extra["year"] = params["year"]

    previous = [run.previous_record(rel) for rel in rels]
    if all(p is not None and p.extra.get("signature") == signature for p in previous):
        for rel in rels:
            run.reuse(rel, url=archive, extra=extra)
        return

    token = os.environ.get(params["token_env"], "").strip()
    try:
        if not token:
            raise AuthError(f"falta {params['token_env']}")
        _check_token_expiry(run, token)
        _build_crops(run, archive, tiles, params, rels, token)
    except AuthError as exc:
        if not all(previous):
            raise
        run.warn(
            f"Earthdata no autorizó la descarga ({exc}): se reusa el recorte de la corrida "
            f"{run.previous_run_id}, que puede no corresponder al listado actual."
        )
        for rel, record in zip(rels, previous, strict=True):
            run.reuse(rel, url=archive, extra=record.extra)
        return
    for rel in rels:
        run.commit(rel, run.part_path(rel), url=archive, extra=extra)


def _save_listing(run: BronzeRun, rel: str, url: str) -> None:
    """Guarda el listado de LAADS sin el mtime del directorio.

    LAADS actualiza ese mtime aunque ningún archivo cambie (visto entre las dos
    primeras corridas: 540 entradas idénticas y solo ese campo distinto). Pasa a
    metadata.json para que el checksum dependa solo de las entradas.
    """
    if run.done(rel) is not None:
        return
    response = run.session.get(url, timeout=(30, 120))
    response.raise_for_status()
    listing, directory_mtime = strip_directory_mtime(response.json())
    run.extra["listing_directory_mtime"] = directory_mtime
    data = json.dumps(listing, ensure_ascii=False, separators=(",", ":")) + "\n"
    run.write_bytes(rel, data.encode("utf-8"), url=url)


def strip_directory_mtime(listing: object) -> tuple[object, int | None]:
    if isinstance(listing, dict) and "mtime" in listing:
        listing = dict(listing)
        return listing, listing.pop("mtime")
    return listing, None


def select_tiles(listing: object, product: str, year: int, wanted: Sequence[str]) -> list[dict]:
    items = listing["content"] if isinstance(listing, dict) else listing
    pattern = re.compile(rf"^{product}\.A{year}001\.(h\d{{2}}v\d{{2}})\.\d{{3}}\.\d{{13}}\.h5$")
    by_tile: dict[str, dict] = {}
    for item in items:
        match = pattern.match(item.get("name", ""))
        if match and match.group(1) in wanted:
            if match.group(1) in by_tile:
                raise IngestError(f"tesela {match.group(1)} repetida en el listado")
            by_tile[match.group(1)] = item
    missing = sorted(set(wanted) - by_tile.keys())
    if missing:
        raise IngestError(f"el listado de {product} {year} no tiene las teselas {missing}")
    return [by_tile[t] for t in sorted(by_tile)]


def tile_bounds(tile: str) -> tuple[int, int, int, int]:
    """(sur, oeste, norte, este) de una tesela hXXvYY de la grilla de 10°."""
    match = re.fullmatch(r"h(\d{2})v(\d{2})", tile)
    if not match:
        raise ValueError(tile)
    west = -180 + TILE_DEGREES * int(match.group(1))
    north = 90 - TILE_DEGREES * int(match.group(2))
    return north - TILE_DEGREES, west, north, west + TILE_DEGREES


def paste(mosaic, crop_bbox: Sequence[float], tile_array, tile_box: Sequence[float], ppd: int):
    """Copia la parte de tile_array que cae dentro del mosaico. Ambos van de norte a sur
    y de oeste a este, con ppd píxeles por grado y bordes alineados a la grilla."""
    row_offset = round((crop_bbox[2] - tile_box[2]) * ppd)
    col_offset = round((tile_box[1] - crop_bbox[1]) * ppd)
    rows, cols = tile_array.shape
    r0, r1 = max(0, row_offset), min(mosaic.shape[0], row_offset + rows)
    c0, c1 = max(0, col_offset), min(mosaic.shape[1], col_offset + cols)
    if r0 >= r1 or c0 >= c1:
        return
    mosaic[r0:r1, c0:c1] = tile_array[
        r0 - row_offset : r1 - row_offset, c0 - col_offset : c1 - col_offset
    ]


def _build_crops(run, archive, tiles, params, rels, token) -> None:
    import h5py
    import numpy as np

    south, west, north, east = params["crop_bbox"]
    ppd = PIXELS_PER_DEGREE
    shape = (round((north - south) * ppd), round((east - west) * ppd))
    mosaics: dict[str, object] = {}
    meta: dict[str, dict] = {}

    with tempfile.TemporaryDirectory(prefix="viirs-") as tmp:
        for item in tiles:
            tile = re.search(r"\.(h\d{2}v\d{2})\.", item["name"]).group(1)
            path = Path(tmp) / item["name"]
            _download_tile(run, f"{archive.rstrip('/')}/{item['name']}", path, item["size"], token)
            with h5py.File(path, "r") as h5:
                box = tile_bounds(tile)
                attrs = h5.attrs
                declared = tuple(
                    round(float(attrs[k]))
                    for k in (
                        "SouthBoundingCoord",
                        "WestBoundingCoord",
                        "NorthBoundingCoord",
                        "EastBoundingCoord",
                    )
                )
                if declared != box:
                    raise IngestError(f"{tile}: bordes {declared} distintos de los esperados {box}")
                for layer in params["layers"]:
                    dataset = h5[f"{GRID_PATH}/{layer}"]
                    fill = dataset.attrs["_FillValue"][0]
                    if layer not in mosaics:
                        mosaics[layer] = np.full(shape, fill, dtype=dataset.dtype)
                        meta[layer] = {
                            "nodata": fill.item(),
                            "units": dataset.attrs["units"].decode(),
                            "long_name": dataset.attrs["long_name"].decode(),
                        }
                    paste(mosaics[layer], params["crop_bbox"], dataset[...], box, ppd)
            path.unlink()

    import rasterio
    from rasterio.transform import from_origin

    transform = from_origin(west, north, 1 / ppd, 1 / ppd)
    for layer, rel in zip(params["layers"], rels, strict=True):
        array = mosaics[layer]
        floating = array.dtype.kind == "f"
        profile = {
            "driver": "GTiff",
            "dtype": array.dtype.name,
            "count": 1,
            "width": shape[1],
            "height": shape[0],
            "crs": "EPSG:4326",
            "transform": transform,
            "nodata": meta[layer]["nodata"],
            "compress": "deflate",
            "predictor": 3 if floating else 2,
            "tiled": True,
            "blockxsize": 512,
            "blockysize": 512,
        }
        with rasterio.open(run.part_path(rel), "w", **profile) as out:
            out.write(array, 1)
            out.update_tags(
                product=params["product"],
                year=str(params["year"]),
                layer=layer,
                units=meta[layer]["units"],
                long_name=meta[layer]["long_name"],
            )


def _download_tile(run: BronzeRun, url: str, path: Path, size: int, token: str) -> None:
    response = run.session.get(
        url, headers={"Authorization": f"Bearer {token}"}, stream=True, timeout=(30, 600)
    )
    with response:
        host = response.url.split("/")[2]
        content_type = response.headers.get("Content-Type", "")
        if response.status_code in (401, 403) or "urs.earthdata" in host or "html" in content_type:
            raise AuthError(f"HTTP {response.status_code} desde {host}")
        response.raise_for_status()
        written = write_stream(path, response.iter_content(CHUNK))
    if written != size:
        raise IngestError(f"{path.name}: se bajaron {written} bytes y el listado dice {size}")
    with path.open("rb") as f:
        if f.read(8) != b"\x89HDF\r\n\x1a\n":
            raise IngestError(f"{path.name}: no es un HDF5")


def _check_token_expiry(run: BronzeRun, token: str) -> None:
    """Lee el vencimiento del token (claim exp del JWT) sin registrarlo ni imprimirlo."""
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        expires = int(claims["exp"])
    except (IndexError, KeyError, ValueError):
        run.warn("no se pudo leer el vencimiento del token de Earthdata")
        return
    if expires <= time.time():
        raise AuthError("el token venció")
    expires_at = datetime.fromtimestamp(expires, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    run.extra["token_expires_at"] = expires_at
    days = (expires - time.time()) / 86400
    if days < TOKEN_WARNING_DAYS:
        run.warn(f"el token de Earthdata vence en {days:.0f} días ({expires_at})")
