"""Base común de la ingesta Bronze (reglas/03).

Cada fuente escribe en data/bronze/<source>/run_id=<id>/ sus archivos crudos y, al
terminar, un metadata.json con fetched_at, el checksum de cada archivo y el del
conjunto. El módulo de cada fuente (pipeline/sources/<id>.py) solo decide qué
pedir; esta base resuelve:

- Escritura atómica: todo se escribe en un .part y se renombra al final.
- Idempotencia contra la corrida anterior: las descargas HTTP son condicionales
  (ETag / Last-Modified). Con un 304, o cuando el módulo verifica que su entrada no
  cambió, el archivo se reusa de la corrida anterior en lugar de bajarse de nuevo.
- Reanudación dentro de la corrida: cada archivo terminado queda anotado en
  _progress.jsonl. Si Airflow reintenta la tarea, no se vuelve a pedir lo que ya
  está: nunca se consulta dos veces lo mismo en una corrida.
"""

from __future__ import annotations

import gzip
import hashlib
import importlib
import json
import os
import re
import shutil
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from pipeline.sources.registry import Registry, Source, load_registry

RUN_ID = re.compile(r"^\d{8}T\d{6}Z$")
METADATA = "metadata.json"
PROGRESS = "_progress.jsonl"
REPORTS_DIR = "_runs"
CHUNK = 1 << 20
# (conexión, lectura) en segundos para requests.
TIMEOUT = (30, 300)

# Firmas de archivo que se controlan antes de aceptar una descarga.
MAGIC = {".zip": b"PK\x03\x04", ".gz": b"\x1f\x8b", ".h5": b"\x89HDF\r\n\x1a\n"}


class IngestError(RuntimeError):
    """La fuente devolvió algo que no se puede guardar como Bronze."""


def bronze_root() -> Path:
    return Path(os.environ.get("ATLAS_DATA_DIR", "data")) / "bronze"


def make_run_id(when: datetime) -> str:
    """run_id ordenable: AAAAMMDDThhmmssZ en UTC."""
    return when.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def http_session(user_agent: str) -> requests.Session:
    """Sesión con User-Agent propio y reintentos con backoff ante 429 y 5xx."""
    retry = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD", "POST"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    session = requests.Session()
    session.headers["User-Agent"] = user_agent
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


@dataclass
class FileRecord:
    path: str
    bytes: int
    sha256: str
    url: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    # run_id del que se copió el archivo sin volver a bajarlo.
    reused_from: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileRecord:
        return cls(**data)


class BronzeRun:
    """Una ingesta de una fuente en una corrida."""

    def __init__(
        self, registry: Registry, source: Source, run_id: str, root: Path | None = None
    ) -> None:
        if not RUN_ID.match(run_id):
            raise ValueError(f"run_id inválido: {run_id!r}")
        self.registry = registry
        self.source = source
        self.run_id = run_id
        self.source_dir = (root or bronze_root()) / source.id
        self.dir = self.source_dir / f"run_id={run_id}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.previous = self._load_previous()
        self._done = self._load_progress()
        self.warnings: list[str] = []
        self.extra: dict[str, Any] = {}
        self.session = http_session(registry.user_agent)

    # Estado ----------------------------------------------------------------

    @property
    def complete(self) -> bool:
        return (self.dir / METADATA).is_file()

    @property
    def previous_run_id(self) -> str | None:
        return self.previous["run_id"] if self.previous else None

    def path(self, rel: str) -> Path:
        parts = PurePosixPath(rel).parts
        if not parts or rel.startswith("/") or ".." in parts or parts[-1].startswith("_"):
            raise ValueError(f"ruta de Bronze inválida: {rel!r}")
        return self.dir.joinpath(*parts)

    def done(self, rel: str) -> FileRecord | None:
        """El archivo ya se guardó en esta corrida (por ejemplo, antes de un reintento)."""
        return self._done.get(rel)

    def previous_record(self, rel: str) -> FileRecord | None:
        if not self.previous:
            return None
        for item in self.previous["files"]:
            if item["path"] == rel:
                record = FileRecord.from_dict(item)
                prev_path = self.source_dir / f"run_id={self.previous['run_id']}" / rel
                return record if prev_path.is_file() else None
        return None

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    # Escritura ---------------------------------------------------------------

    def part_path(self, rel: str) -> Path:
        target = self.path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        return target.with_name(target.name + ".part")

    def commit(self, rel: str, part: Path, **meta: Any) -> FileRecord:
        """Mueve un .part a su lugar definitivo y lo anota."""
        target = self.path(rel)
        _check_magic(rel, part)
        os.replace(part, target)
        record = FileRecord(
            path=rel, bytes=target.stat().st_size, sha256=sha256_file(target), **meta
        )
        self._remember(record)
        return record

    def write_bytes(self, rel: str, data: bytes, **meta: Any) -> FileRecord:
        if (record := self.done(rel)) is not None:
            return record
        part = self.part_path(rel)
        part.write_bytes(data)
        return self.commit(rel, part, **meta)

    def reuse(self, rel: str, **meta: Any) -> FileRecord:
        """Copia (o enlaza) el archivo de la corrida anterior sin volver a pedirlo."""
        previous = self.previous_record(rel)
        if previous is None:
            raise IngestError(f"{rel}: no hay corrida anterior para reusar")
        source_path = self.source_dir / f"run_id={self.previous['run_id']}" / rel
        part = self.part_path(rel)
        part.unlink(missing_ok=True)
        try:
            os.link(source_path, part)
        except OSError:
            shutil.copyfile(source_path, part)
        if sha256_file(part) != previous.sha256:
            part.unlink()
            raise IngestError(
                f"{rel}: el archivo de la corrida anterior no coincide con su checksum"
            )
        return self.commit(
            rel,
            part,
            url=meta.pop("url", previous.url),
            etag=meta.pop("etag", previous.etag),
            last_modified=meta.pop("last_modified", previous.last_modified),
            reused_from=previous.reused_from or self.previous["run_id"],
            extra=meta.pop("extra", previous.extra),
        )

    def download(
        self,
        rel: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        conditional: bool = True,
        validate: Callable[[Path, requests.Response], None] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> FileRecord:
        """GET a un archivo de Bronze. Si conditional, usa el ETag de la corrida anterior."""
        if (record := self.done(rel)) is not None:
            return record
        request_headers = dict(headers or {})
        previous = self.previous_record(rel) if conditional else None
        if previous is not None and previous.url == url:
            if previous.etag:
                request_headers["If-None-Match"] = previous.etag
            if previous.last_modified:
                request_headers["If-Modified-Since"] = previous.last_modified
        else:
            previous = None

        with self.session.get(
            url, params=params, headers=request_headers, stream=True, timeout=TIMEOUT
        ) as response:
            if response.status_code == 304 and previous is not None:
                return self.reuse(rel, url=url, extra=extra or previous.extra)
            response.raise_for_status()
            part = self.part_path(rel)
            write_stream(part, response.iter_content(CHUNK))
            if validate is not None:
                try:
                    validate(part, response)
                except Exception:
                    part.unlink(missing_ok=True)
                    raise
            return self.commit(
                rel,
                part,
                url=url,
                etag=response.headers.get("ETag"),
                last_modified=response.headers.get("Last-Modified"),
                extra=extra or {},
            )

    def read_json(self, rel: str) -> Any:
        return json.loads(self.path(rel).read_text(encoding="utf-8"))

    # Cierre ------------------------------------------------------------------

    def finish(self) -> dict[str, Any]:
        """Escribe metadata.json. Sin él, la corrida de esta fuente no cuenta como hecha."""
        files = sorted(self._done.values(), key=lambda r: r.path)
        if not files:
            raise IngestError(f"{self.source.id}: la ingesta no guardó ningún archivo")
        checksum = aggregate_checksum(files)
        previous_checksum = self.previous["checksum"] if self.previous else None
        metadata = {
            "source": self.source.id,
            "kind": self.source.kind,
            "run_id": self.run_id,
            "fetched_at": utc_now(),
            "url": self.source.url,
            "license": self.source.license,
            "attribution": self.source.attribution,
            "params_sha256": sha256_json(self.source.params),
            "checksum": checksum,
            "previous_run_id": self.previous_run_id,
            "unchanged_vs_previous": checksum == previous_checksum,
            "bytes": sum(f.bytes for f in files),
            "files": [asdict(f) for f in files],
            "warnings": self.warnings,
            "extra": self.extra,
        }
        target = self.dir / METADATA
        part = target.with_name(METADATA + ".part")
        part.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(part, target)
        (self.dir / PROGRESS).unlink(missing_ok=True)
        return summarize(metadata)

    def metadata(self) -> dict[str, Any]:
        return json.loads((self.dir / METADATA).read_text(encoding="utf-8"))

    # Internos ----------------------------------------------------------------

    def _remember(self, record: FileRecord) -> None:
        self._done[record.path] = record
        with (self.dir / PROGRESS).open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(record), ensure_ascii=False, sort_keys=True) + "\n")

    def _load_progress(self) -> dict[str, FileRecord]:
        progress = self.dir / PROGRESS
        if not progress.is_file():
            return {}
        done: dict[str, FileRecord] = {}
        for line in progress.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = FileRecord.from_dict(json.loads(line))
            target = self.path(record.path)
            if target.is_file() and target.stat().st_size == record.bytes:
                done[record.path] = record
        return done

    def _load_previous(self) -> dict[str, Any] | None:
        """Metadata de la última corrida completa anterior a esta."""
        candidates = sorted(
            p
            for p in self.source_dir.glob("run_id=*")
            if p.name.removeprefix("run_id=") < self.run_id and (p / METADATA).is_file()
        )
        if not candidates:
            return None
        return json.loads((candidates[-1] / METADATA).read_text(encoding="utf-8"))


def write_stream(part: Path, chunks: Iterable[bytes]) -> int:
    size = 0
    with part.open("wb") as f:
        for chunk in chunks:
            if chunk:
                f.write(chunk)
                size += len(chunk)
    return size


def aggregate_checksum(files: Iterable[FileRecord]) -> str:
    """sha256 del conjunto: depende solo de las rutas y del contenido de los archivos."""
    lines = "".join(f"{f.path}\t{f.sha256}\n" for f in sorted(files, key=lambda r: r.path))
    return "sha256:" + hashlib.sha256(lines.encode("utf-8")).hexdigest()


def summarize(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": metadata["source"],
        "run_id": metadata["run_id"],
        "files": len(metadata["files"]),
        "bytes": metadata["bytes"],
        "reused_files": sum(1 for f in metadata["files"] if f["reused_from"]),
        "checksum": metadata["checksum"],
        "previous_run_id": metadata["previous_run_id"],
        "unchanged_vs_previous": metadata["unchanged_vs_previous"],
        "warnings": metadata["warnings"],
    }


def _check_magic(rel: str, part: Path) -> None:
    expected = MAGIC.get(Path(rel).suffix)
    if expected is None:
        return
    with part.open("rb") as f:
        head = f.read(len(expected))
    if head != expected:
        part.unlink(missing_ok=True)
        raise IngestError(f"{rel}: no tiene la firma de un {Path(rel).suffix}")


# Ayudas para tipos de fuente ----------------------------------------------------


def file_suffix(url: str) -> str:
    """Extensión de un archivo remoto, incluidas las dobles como .gpkg.gz."""
    name = PurePosixPath(url.split("?", 1)[0]).name
    suffixes = PurePosixPath(name).suffixes
    if len(suffixes) >= 2 and suffixes[-1] == ".gz":
        return "".join(suffixes[-2:])
    return suffixes[-1] if suffixes else ""


def download_files(run: BronzeRun) -> None:
    """Fuentes http_files: cada archivo del registro tal cual, con descarga condicional."""
    for item in run.source.params["files"]:
        rel = item["name"] + file_suffix(item["url"])
        validate = _validate_gzip if rel.endswith(".gz") else None
        run.download(rel, item["url"], validate=validate)


def _validate_gzip(part: Path, _response: requests.Response) -> None:
    # Lee el gzip completo: detecta descargas truncadas, que la firma no ve.
    try:
        with gzip.open(part, "rb") as f:
            while f.read(CHUNK):
                pass
    except (EOFError, OSError) as exc:
        raise IngestError(f"{part.name}: gzip incompleto o dañado ({exc})") from exc


# Orquestación -------------------------------------------------------------------

# Módulos de pipeline/sources/ que no son fuentes.
INFRA_MODULES = frozenset({"base", "registry"})


def source_module(source_id: str):
    return importlib.import_module(f"pipeline.sources.{source_id}")


def ingest_source(
    source_id: str,
    run_id: str,
    *,
    registry: Registry | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Ingesta una fuente del registro. Si ya terminó en esta corrida, no hace nada."""
    registry = registry or load_registry()
    run = BronzeRun(registry, registry.get(source_id), run_id, root)
    if run.complete:
        return summarize(run.metadata())
    source_module(source_id).ingest(run)
    return run.finish()


def write_run_report(
    run_id: str, summaries: Iterable[dict[str, Any]], root: Path | None = None
) -> dict[str, Any]:
    """Informe de la corrida en data/bronze/_runs/run_id=<id>.json."""
    items = sorted(summaries, key=lambda s: s["source"])
    report = {
        "run_id": run_id,
        "written_at": utc_now(),
        "bytes": sum(s["bytes"] for s in items),
        "files": sum(s["files"] for s in items),
        "sources": items,
    }
    out_dir = (root or bronze_root()) / REPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"run_id={run_id}.json"
    target.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report
