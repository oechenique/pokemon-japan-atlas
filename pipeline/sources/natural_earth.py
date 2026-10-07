"""natural_earth: los zips de Natural Earth 10m tal cual (dominio público).

Descarga condicional: si el ETag no cambió, se reusa el zip de la corrida anterior.
"""

from __future__ import annotations

from pipeline.sources.base import BronzeRun, download_files


def ingest(run: BronzeRun) -> None:
    download_files(run)
