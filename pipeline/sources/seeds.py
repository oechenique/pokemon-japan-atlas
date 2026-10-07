"""seeds: los CSV curados de pipeline/seeds/, copiados tal cual a Bronze.

Antes de copiarlos se controla lo mínimo de reglas/03: columnas exigidas, una
source_url https por fila (nunca Bulbapedia, reglas/00), las URLs opcionales de
other_sources con las mismas reglas y un confidence válido.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from pipeline.sources.base import BronzeRun, IngestError

PIPELINE_DIR = Path(__file__).resolve().parents[1]
CONFIDENCE = frozenset({"oficial", "ampliamente aceptada", "teoría de fans"})
FORBIDDEN_HOSTS = ("bulbapedia", "bulbagarden")
# Grupo editorial de cada dominio citado. "ampliamente aceptada" exige fuentes de al
# menos dos grupos distintos: TheGamer, GameRant y CBR son todos de Valnet y cuentan
# como uno. Un dominio nuevo hay que asignarlo acá antes de citarlo.
PUBLISHER_GROUPS = {
    "thegamer.com": "valnet",
    "gamerant.com": "valnet",
    "cbr.com": "valnet",
    "wikidata.org": "wikidata",
    "wikipedia.org": "wikipedia",
    "x.com": "oficial",
    "nintendo.co.jp": "oficial",
    "pokemon.co.jp": "oficial",
    "web.archive.org": "oficial",
}


def ingest(run: BronzeRun) -> None:
    seeds_dir = PIPELINE_DIR / run.source.params["dir"]
    for item in run.source.params["files"]:
        data = (seeds_dir / item["file"]).read_bytes()
        errors = validate_seed(data, item["required_columns"])
        if errors:
            raise IngestError(f"seed {item['name']} inválido:\n- " + "\n- ".join(errors))
        rows = len(data.decode("utf-8").splitlines()) - 1
        run.write_bytes(f"{item['name']}.csv", data, extra={"rows": rows, "file": item["file"]})


def validate_seed(data: bytes, required_columns: list[str]) -> list[str]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return ["el archivo no está en UTF-8"]
    reader = csv.DictReader(io.StringIO(text, newline=""))
    missing = set(required_columns) - set(reader.fieldnames or [])
    if missing:
        return [f"faltan columnas {sorted(missing)}"]
    errors = []
    rows = 0
    for line, row in enumerate(reader, start=2):
        rows += 1
        url = (row.get("source_url") or "").strip()
        if not url.startswith("https://"):
            errors.append(f"línea {line}: source_url tiene que ser https")
        elif any(host in url.lower() for host in FORBIDDEN_HOSTS):
            errors.append(f"línea {line}: Bulbapedia no se usa como fuente (reglas/00)")
        for other in (row.get("other_sources") or "").split():
            if not other.startswith("https://"):
                errors.append(f"línea {line}: other_sources tiene que ser URLs https")
            elif any(host in other.lower() for host in FORBIDDEN_HOSTS):
                errors.append(f"línea {line}: Bulbapedia no se usa como fuente (reglas/00)")
        if "source_groups" in row:
            errors += _check_groups(row, line)
        if "confidence" in row and row["confidence"] not in CONFIDENCE:
            errors.append(
                f"línea {line}: confidence {row['confidence']!r} no es {sorted(CONFIDENCE)}"
            )
        empty = [c for c in required_columns if not (row.get(c) or "").strip()]
        if empty:
            errors.append(f"línea {line}: columnas vacías {empty}")
    if rows == 0:
        errors.append("el seed no tiene filas")
    return errors


def publisher_group(url: str) -> str | None:
    host = url.split("/")[2].lower() if url.count("/") >= 2 else ""
    for domain, group in PUBLISHER_GROUPS.items():
        if host == domain or host.endswith("." + domain):
            return group
    return None


def _check_groups(row: dict[str, str], line: int) -> list[str]:
    urls = [row.get("source_url") or "", *(row.get("other_sources") or "").split()]
    groups = {publisher_group(u) for u in urls if u}
    if None in groups:
        unknown = [u for u in urls if u and publisher_group(u) is None]
        return [f"línea {line}: dominio sin grupo editorial en PUBLISHER_GROUPS: {unknown[0]}"]
    declared = set((row.get("source_groups") or "").split())
    errors = []
    if declared != groups:
        errors.append(
            f"línea {line}: source_groups {sorted(declared)} no coincide con {sorted(groups)}"
        )
    if row.get("confidence") == "ampliamente aceptada" and len(groups) < 2:
        errors.append(
            f"línea {line}: 'ampliamente aceptada' necesita dos grupos editoriales distintos"
        )
    return errors
