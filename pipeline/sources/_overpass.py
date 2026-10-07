"""Cliente de Overpass que comparten osm_overpass y osm_buildings (reglas/03).

- Una sola instancia (overpass.endpoint), consultas por bbox o around, nunca `area`.
- Una consulta por vez en todo el contenedor (lock de archivo) y pausa entre consultas.
- Un `remark` en la respuesta cuenta como falla, aunque venga con HTTP 200.
- La respuesta se guarda cruda, salvo osm3s.timestamp_osm_base: cambia cada minuto
  aunque los datos no cambien, así que pasa a metadata.json y el checksum queda
  dependiendo solo de los datos.

Modo de desarrollo: con OVERPASS_MODE=reuse (en .env; el default es query) no se
consulta Overpass: cada archivo se copia de la última corrida completa, siempre que
la consulta sea idéntica (mismos selectores, bbox y snapshot_date). Si falta el
archivo anterior o la consulta cambió, la ingesta falla en lugar de consultar.
metadata.json lo deja registrado: extra.overpass_mode, un aviso en warnings y
reused_from en cada archivo. La corrida de publicación tiene que usar query.

OVERPASS_MODE=reuse_or_query hace lo mismo, pero consulta las consultas que no están en
la corrida anterior (por ejemplo, una categoría nueva) en lugar de fallar. Sirve para
traer solo lo nuevo; también queda marcado y tampoco sirve para publicar.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import re
import tempfile
import time
from collections.abc import Iterator, Sequence
from pathlib import Path

from pipeline.sources.base import CHUNK, BronzeRun, FileRecord, IngestError

LOCK_PATH = Path(tempfile.gettempdir()) / "atlas-overpass.lock"
# Hasta dónde se busca la cabecera osm3s antes de "elements".
HEADER_LIMIT = 64 * 1024
TIMESTAMP_LINE = re.compile(
    rb'^[ \t]*"(timestamp_osm_base|timestamp_areas_base)":[ \t]*"([^"]*)",[ \t]*\r?\n', re.M
)
REMARK = re.compile(rb'"remark":\s*"((?:[^"\\]|\\.)*)"')
TAIL_BYTES = 4096
MODE_ENV = "OVERPASS_MODE"
MODES = frozenset({"query", "reuse", "reuse_or_query"})
REUSING = frozenset({"reuse", "reuse_or_query"})
# Tipos de fuente del registro que consultan Overpass.
KINDS = frozenset({"overpass", "overpass_around"})


class OverpassError(IngestError):
    """Overpass respondió con un error (incluido un remark con HTTP 200)."""


def mode() -> str:
    value = os.environ.get(MODE_ENV, "").strip().lower() or "query"
    if value not in MODES:
        raise IngestError(f"{MODE_ENV}={value!r} no es uno de {sorted(MODES)}")
    return value


def build_query(
    selectors: Sequence[str],
    out: str,
    *,
    timeout_s: int,
    bbox: Sequence[float] | None = None,
    around: tuple[int, float, float] | None = None,
    snapshot_date: str | None = None,
) -> str:
    """Arma la consulta en Overpass QL. bbox es [sur, oeste, norte, este]; around es
    (radio_m, lat, lon)."""
    if (bbox is None) == (around is None):
        raise ValueError("hace falta bbox o around, no los dos")
    settings = f"[out:json][timeout:{timeout_s}]"
    if bbox is not None:
        settings += "[bbox:{},{},{},{}]".format(*bbox)
    if snapshot_date:
        settings += f'[date:"{snapshot_date}"]'
    suffix = "" if around is None else "(around:{},{},{})".format(*around)
    body = "".join(f"{selector}{suffix};" for selector in selectors)
    return f"{settings};({body});out {out};"


def fetch(run: BronzeRun, rel: str, query: str) -> FileRecord:
    """Ejecuta una consulta y guarda la respuesta en Bronze (una sola vez por corrida)."""
    if (record := run.done(rel)) is not None:
        return record
    current = mode()
    if current == "reuse" or (current == "reuse_or_query" and _reusable(run, rel, query)):
        return _reuse(run, rel, query)
    config = run.registry.overpass
    with _exclusive(LOCK_PATH):
        try:
            response = run.session.post(
                config["endpoint"],
                data={"data": query},
                stream=True,
                timeout=(30, config["timeout_s"] + 60),
            )
            with response:
                if response.status_code != 200:
                    raise OverpassError(
                        f"{rel}: HTTP {response.status_code} de Overpass: {response.text[:300]!r}"
                    )
                part = run.part_path(rel)
                timestamps = write_without_timestamps(part, response.iter_content(CHUNK))
        finally:
            time.sleep(config["pause_s"])
    try:
        check_remark(part)
    except OverpassError:
        part.unlink(missing_ok=True)
        raise
    return run.commit(
        rel,
        part,
        url=config["endpoint"],
        extra={"query": query, **timestamps},
    )


def _reusable(run: BronzeRun, rel: str, query: str) -> bool:
    previous = run.previous_record(rel)
    return previous is not None and previous.extra.get("query") == query


def _reuse(run: BronzeRun, rel: str, query: str) -> FileRecord:
    previous = run.previous_record(rel)
    if previous is None:
        raise IngestError(
            f"{MODE_ENV}=reuse: {rel} no está en la corrida anterior ({run.previous_run_id}); "
            f"corré con {MODE_ENV}=query"
        )
    if previous.extra.get("query") != query:
        raise IngestError(
            f"{MODE_ENV}=reuse: la consulta de {rel} cambió desde la corrida "
            f"{run.previous_run_id}; corré con {MODE_ENV}=query"
        )
    return run.reuse(rel, extra=previous.extra)


def finalize(run: BronzeRun, **extra: object) -> None:
    """Datos de la fuente que van a metadata.json. Se calcula al cerrar la fuente, no
    en cada consulta: en atlas_run cada consulta corre en su propia tarea."""
    current = mode()
    run.extra.update(
        overpass_mode=current, snapshot_date=run.registry.overpass["snapshot_date"], **extra
    )
    if current in REUSING:
        run.warn(
            f"{MODE_ENV}={current}: Overpass no se consultó (o solo para lo que faltaba); los "
            "archivos reusados se copiaron del Bronze anterior (ver reused_from). No sirve "
            "para la corrida de publicación."
        )


def fetch_planned(item: dict[str, str], run_id: str, *, registry=None, root=None) -> dict:
    """Una consulta del plan de atlas_run (ver plan_queries), en su propia tarea."""
    from pipeline.sources.registry import load_registry

    registry = registry or load_registry()
    run = BronzeRun(registry, registry.get(item["source"]), run_id, root)
    if run.complete:
        raise IngestError(f"{item['source']} ya está cerrada en la corrida {run_id}")
    record = fetch(run, item["rel"], item["query"])
    return {
        "source": item["source"],
        "path": record.path,
        "bytes": record.bytes,
        "sha256": record.sha256,
        "reused_from": record.reused_from,
    }


def plan_queries(registry) -> list[dict[str, str]]:
    """Todas las consultas a Overpass de la corrida, de todas las fuentes que lo usan."""
    from pipeline.sources.base import source_module

    plan = []
    for source in registry.sources:
        if source.kind in KINDS:
            for rel, query in source_module(source.id).queries(registry, source):
                plan.append({"source": source.id, "rel": rel, "query": query})
    return plan


def write_without_timestamps(part: Path, chunks: Iterator[bytes]) -> dict[str, str]:
    """Escribe la respuesta sin las líneas de timestamp de osm3s y las devuelve."""
    chunks = iter(chunks)
    head = b""
    for chunk in chunks:
        head += chunk
        if b'"elements"' in head or len(head) > HEADER_LIMIT:
            break
    if not head.lstrip().startswith(b"{"):
        raise OverpassError(f"la respuesta de Overpass no es JSON: {head[:200]!r}")
    marker = head.find(b'"elements"')
    header, rest = (head, b"") if marker < 0 else (head[:marker], head[marker:])
    timestamps = {m.group(1).decode(): m.group(2).decode() for m in TIMESTAMP_LINE.finditer(header)}
    with part.open("wb") as f:
        f.write(TIMESTAMP_LINE.sub(b"", header))
        f.write(rest)
        for chunk in chunks:
            f.write(chunk)
    return timestamps


def check_remark(part: Path) -> None:
    """Overpass agrega "remark" al final cuando la consulta falló (timeout, memoria)."""
    with part.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - TAIL_BYTES))
        tail = f.read()
    match = REMARK.search(tail)
    if match:
        raise OverpassError(f"{part.name}: remark de Overpass: {match.group(1).decode()[:300]}")
    if not tail.rstrip().endswith(b"}"):
        raise OverpassError(f"{part.name}: la respuesta de Overpass quedó truncada")


@contextlib.contextmanager
def _exclusive(path: Path) -> Iterator[None]:
    with path.open("a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
