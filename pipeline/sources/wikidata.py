"""wikidata: las consultas SPARQL de queries/, una respuesta JSON por consulta (CC0).

Se consulta en cada corrida (plan de la Fase 1). Las consultas ordenan por todas
sus columnas, así que si Wikidata no cambió, el checksum tampoco.
"""

from __future__ import annotations

import json
from pathlib import Path

import requests

from pipeline.sources.base import BronzeRun, IngestError, sha256_file
from pipeline.sources.registry import SOURCES_DIR


def ingest(run: BronzeRun) -> None:
    for query in run.source.params["queries"]:
        path = SOURCES_DIR / query["file"]
        run.download(
            f"{query['id']}.json",
            run.source.url,
            params={"query": path.read_text(encoding="utf-8"), "format": "json"},
            headers={"Accept": "application/sparql-results+json"},
            conditional=False,
            validate=_validate_results,
            extra={"query_file": query["file"], "query_sha256": sha256_file(path)},
        )


def _validate_results(part: Path, _response: requests.Response) -> None:
    data = json.loads(part.read_text(encoding="utf-8"))
    bindings = data.get("results", {}).get("bindings")
    if not isinstance(bindings, list) or not bindings:
        raise IngestError(f"{part.name}: la consulta SPARQL no devolvió filas")
