"""pokeapi: solo datos factuales (reglas/00). Nunca imágenes ni recursos con sprites.

Por cada recurso permitido (generation, region) se guarda el índice y el detalle de
cada elemento: <recurso>/index.json y <recurso>/<nombre>.json.
"""

from __future__ import annotations

import re
from pathlib import Path

import requests

from pipeline.sources.base import BronzeRun, IngestError
from pipeline.sources.registry import POKEAPI_ALLOWED_RESOURCES

NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
# Ninguna respuesta guardada puede traer referencias a imágenes.
IMAGE_MARKERS = (b'"sprites"', b'"front_default"', b".png", b".svg", b".gif")


def ingest(run: BronzeRun) -> None:
    base = run.source.url
    for resource in run.source.params["resources"]:
        if resource not in POKEAPI_ALLOWED_RESOURCES:
            raise IngestError(f"recurso de PokeAPI no permitido: {resource}")
        prefix = f"{base}{resource}/"
        index_rel = f"{resource}/index.json"
        run.download(index_rel, f"{prefix}?limit=1000", validate=_no_images)
        index = run.read_json(index_rel)
        if index.get("next"):
            raise IngestError(f"{resource}: el índice tiene más de una página")
        for item in sorted(index["results"], key=lambda r: r["name"]):
            name, url = item["name"], item["url"]
            if not NAME.match(name) or not url.startswith(prefix):
                raise IngestError(f"{resource}: elemento inesperado {item!r}")
            run.download(f"{resource}/{name}.json", url, validate=_no_images)


def _no_images(part: Path, _response: requests.Response) -> None:
    data = part.read_bytes()
    found = [marker.decode() for marker in IMAGE_MARKERS if marker in data]
    if found:
        raise IngestError(f"{part.name}: la respuesta trae referencias a imágenes {found}")
