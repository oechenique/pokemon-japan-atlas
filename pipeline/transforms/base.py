"""Base común de Silver (reglas/03): leer Bronze de una corrida y escribir GeoParquet.

- Bronze se lee siempre de la misma corrida (run_id), y solo de fuentes completas
  (con metadata.json).
- Cada entidad se escribe en data/silver/<entidad>.parquet con exactamente las
  columnas de su contrato, en ese orden y con esos tipos (CAST explícito), ordenada
  por la clave primaria. Así el archivo es el mismo byte a byte si los datos no
  cambian.
- El run_id no va dentro del parquet (cambiaría el hash en cada corrida): el linaje
  queda en data/silver/_runs/run_id=<id>.json.
- Las transformaciones no reintentan: si fallan, es un bug (reglas/03).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import duckdb

from pipeline.quality.contracts import Contract, load_contracts
from pipeline.sources.base import METADATA, RUN_ID, sha256_file, utc_now

SILVER = "silver"
RUNS_DIR = "_runs"
GEOMETRY_PARQUET_TYPE = "GEOMETRY('OGC:CRS84')"


class TransformError(RuntimeError):
    """La entrada no permite construir la entidad (por ejemplo, Bronze incompleto)."""


def data_root() -> Path:
    return Path(os.environ.get("ATLAS_DATA_DIR", "data"))


# Tope de memoria por conexión: Airflow corre varias tareas a la vez en el mismo
# contenedor. Si no alcanza, DuckDB vuelca a disco en data/_tmp/duckdb.
MEMORY_LIMIT = os.environ.get("ATLAS_DUCKDB_MEMORY", "2GB")
THREADS = int(os.environ.get("ATLAS_DUCKDB_THREADS", "2"))


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.load_extension("spatial")
    con.load_extension("h3")
    spill = data_root() / "_tmp" / "duckdb"
    spill.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET memory_limit = '{MEMORY_LIMIT}'")
    con.execute(f"SET threads = {THREADS}")
    con.execute(f"SET temp_directory = '{spill.as_posix()}'")
    con.execute("SET enable_progress_bar = false")
    return con


class Bronze:
    """Acceso de solo lectura al Bronze de una corrida."""

    def __init__(self, run_id: str, root: Path | None = None) -> None:
        if not RUN_ID.match(run_id):
            raise ValueError(f"run_id inválido: {run_id!r}")
        self.run_id = run_id
        self.root = (root or data_root()) / "bronze"

    def dir(self, source_id: str) -> Path:
        path = self.root / source_id / f"run_id={self.run_id}"
        if not (path / METADATA).is_file():
            raise TransformError(f"{source_id}: Bronze incompleto en la corrida {self.run_id}")
        return path

    def path(self, source_id: str, rel: str) -> str:
        path = self.dir(source_id) / rel
        if not path.is_file():
            raise TransformError(f"{source_id}: falta {rel} en la corrida {self.run_id}")
        return path.as_posix()

    def zip_member(self, source_id: str, rel: str, member: str) -> str:
        """Ruta GDAL a un archivo dentro de un zip de Bronze (para ST_Read)."""
        return f"/vsizip/{self.path(source_id, rel)}/{member}"

    def metadata(self, source_id: str) -> dict[str, Any]:
        return json.loads((self.dir(source_id) / METADATA).read_text(encoding="utf-8"))

    def json(self, source_id: str, rel: str) -> Any:
        return json.loads(Path(self.path(source_id, rel)).read_text(encoding="utf-8"))


def sparql_rows(data: dict[str, Any], columns: Sequence[str]) -> list[tuple[str | None, ...]]:
    """Filas de una respuesta SPARQL JSON. Las URIs de Wikidata quedan como su Q-id; las
    variables opcionales que faltan, como NULL."""
    rows = []
    for binding in data["results"]["bindings"]:
        row = []
        for column in columns:
            cell = binding.get(column)
            if cell is None:
                row.append(None)
            elif cell["type"] == "uri" and "/entity/" in cell["value"]:
                row.append(cell["value"].rsplit("/", 1)[1])
            else:
                row.append(cell["value"])
        rows.append(tuple(row))
    return rows


def create_table(
    con: duckdb.DuckDBPyConnection,
    name: str,
    columns: Sequence[str],
    rows: Iterable[Sequence[Any]],
) -> None:
    """Tabla temporal de VARCHAR desde filas de Python (respuestas JSON de Bronze)."""
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE {name} ({', '.join(f'{c} VARCHAR' for c in columns)})"
    )
    rows = [tuple(None if v is None else str(v) for v in row) for row in rows]
    if rows:
        placeholders = ", ".join("?" for _ in columns)
        con.executemany(f"INSERT INTO {name} VALUES ({placeholders})", rows)


def silver_path(entity: str, root: Path | None = None) -> Path:
    return (root or data_root()) / SILVER / f"{entity}.parquet"


def write_entity(
    con: duckdb.DuckDBPyConnection,
    entity: str,
    query: str,
    *,
    root: Path | None = None,
    contracts: dict[str, Contract] | None = None,
) -> dict[str, Any]:
    """Escribe la entidad con las columnas de su contrato, ordenada por la clave primaria."""
    contract = (contracts or load_contracts())[entity]
    target = silver_path(entity, root)
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    part.unlink(missing_ok=True)
    select = ", ".join(_cast(column.name, column.type) for column in contract.columns)
    order = ", ".join(contract.primary_key)
    try:
        con.execute(
            f"COPY (SELECT {select} FROM ({query}) ORDER BY {order}) "
            f"TO '{part.as_posix()}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 122880)"
        )
        _check_schema(con, part, contract)
    except Exception:
        part.unlink(missing_ok=True)
        raise
    os.replace(part, target)
    rows = con.execute(f"SELECT count(*) FROM read_parquet('{target.as_posix()}')").fetchone()[0]
    return {
        "entity": entity,
        "rows": rows,
        "bytes": target.stat().st_size,
        "sha256": sha256_file(target),
        "path": f"{SILVER}/{entity}.parquet",
    }


def write_run_lineage(
    run_id: str, summaries: Iterable[dict[str, Any]], root: Path | None = None
) -> dict[str, Any]:
    """Linaje de Silver de la corrida: qué entidades se escribieron, con su hash."""
    items = sorted(summaries, key=lambda s: s["entity"])
    report = {"run_id": run_id, "written_at": utc_now(), "entities": items}
    out = (root or data_root()) / SILVER / RUNS_DIR / f"run_id={run_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def _cast(name: str, type_: str) -> str:
    if type_ == "GEOMETRY":
        # Todas las fuentes vienen en lon/lat sobre WGS84, pero con etiquetas distintas
        # (ST_Read de GeoJSON dice EPSG:4326; ST_Point, ninguna). ST_SetCRS solo cambia
        # la etiqueta, no las coordenadas.
        return f"ST_SetCRS({name}, 'OGC:CRS84') AS {name}"
    return f"CAST({name} AS {type_}) AS {name}"


def _check_schema(con: duckdb.DuckDBPyConnection, path: Path, contract: Contract) -> None:
    described = con.execute(f"DESCRIBE SELECT * FROM read_parquet('{path.as_posix()}')").fetchall()
    actual = [(row[0], row[1]) for row in described]
    # DuckDB lee la geometría con su CRS: OGC:CRS84 es EPSG:4326 en orden lon/lat, el
    # que pide reglas/03. Cualquier otro CRS es un error.
    expected = [
        (c.name, GEOMETRY_PARQUET_TYPE if c.type == "GEOMETRY" else c.type)
        for c in contract.columns
    ]
    if actual != expected:
        raise TransformError(
            f"{contract.entity}: el esquema escrito {actual} no es el del contrato {expected}"
        )
