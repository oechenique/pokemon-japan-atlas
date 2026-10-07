"""kontur_population: el recorte de Japón de Kontur Population (CC BY 4.0), tal cual.

Es el .gpkg.gz de HDX (hexágonos H3 de 400 m). Descarga condicional por ETag y
control de que el gzip esté completo.
"""

from __future__ import annotations

from pipeline.sources.base import BronzeRun, download_files


def ingest(run: BronzeRun) -> None:
    download_files(run)
