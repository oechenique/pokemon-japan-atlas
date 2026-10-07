"""Contratos de las entidades Silver (pipeline/contracts/<entidad>.yaml, reglas/03).

Un contrato fija las columnas, sus tipos y nulabilidad, la clave primaria, la
geometría, los conteos mínimos y qué nulos se reportan. De acá salen los checks del
DQ gate. La validación junta todos los errores de una vez, como la del registro.

Contratos y registro tienen que coincidir en los dos sentidos: cada fuente de un
contrato declara esa entidad en su `feeds`, y cada entidad de un `feeds` tiene
contrato.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from pipeline.sources.registry import Registry

CONTRACTS_DIR = Path(__file__).resolve().parents[1] / "contracts"

TYPES = frozenset(
    {
        "VARCHAR",
        "INTEGER",
        "BIGINT",
        "DOUBLE",
        "BOOLEAN",
        "DATE",
        "TIMESTAMP",
        "VARCHAR[]",
        "GEOMETRY",
    }
)
GEOMETRY_TYPES = frozenset({"POINT", "LINESTRING", "MULTILINESTRING", "POLYGON", "MULTIPOLYGON"})
NUMERIC = frozenset({"INTEGER", "BIGINT", "DOUBLE"})
GEOMETRY_COLUMN = "geometry"
ENTITY = re.compile(r"^[a-z][a-z0-9_]*$")


class ContractError(ValueError):
    """Un contrato no cumple el esquema."""


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    nullable: bool
    pattern: str | None = None
    allowed: tuple[Any, ...] | None = None
    range: tuple[float, float] | None = None


@dataclass(frozen=True)
class Contract:
    entity: str
    description: str
    sources: tuple[str, ...]
    primary_key: tuple[str, ...]
    geometry_types: tuple[str, ...]
    inside_japan: bool
    count_min: int
    count_max: int | None
    count_by_column: str | None
    count_by_min: dict[str, int]
    columns: tuple[Column, ...]
    null_report_columns: tuple[str, ...]
    null_report_by: str | None

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)

    def column(self, name: str) -> Column:
        for column in self.columns:
            if column.name == name:
                return column
        raise KeyError(name)

    @property
    def has_geometry(self) -> bool:
        return bool(self.geometry_types)


def load_contracts(directory: Path = CONTRACTS_DIR) -> dict[str, Contract]:
    raw = {
        path.stem: yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.yaml"))
    }
    errors = []
    for stem, data in raw.items():
        errors += [f"{stem}.yaml: {e}" for e in validate_contract(data, stem)]
    if errors:
        raise ContractError("contratos inválidos:\n- " + "\n- ".join(errors))
    return {stem: _build(data) for stem, data in raw.items()}


def check_registry_consistency(contracts: dict[str, Contract], registry: Registry) -> list[str]:
    """Errores si contratos y `feeds` del registro no coinciden en los dos sentidos."""
    errors = []
    feeds = {source.id: set(source.feeds) for source in registry.sources}
    for contract in contracts.values():
        for source_id in contract.sources:
            if source_id not in feeds:
                errors.append(f"{contract.entity}: la fuente {source_id} no está en el registro")
            elif contract.entity not in feeds[source_id]:
                errors.append(f"{contract.entity}: {source_id} no la declara en su feeds")
    for source_id, entities in feeds.items():
        for entity in sorted(entities):
            if entity not in contracts:
                errors.append(f"{source_id} alimenta {entity}, que no tiene contrato")
            elif source_id not in contracts[entity].sources:
                errors.append(f"{source_id} alimenta {entity}, pero el contrato no la lista")
    return errors


def validate_contract(data: Any, stem: str) -> list[str]:
    if not isinstance(data, dict):
        return ["el contrato tiene que ser un mapeo YAML"]
    errors: list[str] = []
    entity = data.get("entity")
    if not isinstance(entity, str) or not ENTITY.match(entity):
        errors.append("entity inválida")
    elif entity != stem:
        errors.append(f"entity {entity!r} no coincide con el nombre del archivo")
    if not _nonempty_str(data.get("description")):
        errors.append("falta description")
    sources = data.get("sources")
    if not _str_list(sources):
        errors.append("sources tiene que ser una lista no vacía de ids del registro")

    columns = data.get("columns")
    if not isinstance(columns, list) or not columns:
        return errors + ["columns tiene que ser una lista no vacía"]
    names: list[str] = []
    for index, column in enumerate(columns):
        errors += _validate_column(column, index, names)
    by_name = {c["name"]: c for c in columns if isinstance(c, dict) and "name" in c}

    if "license" not in by_name or by_name["license"].get("nullable") is not False:
        errors.append("toda entidad necesita una columna license no nulable (reglas/03)")

    pk = data.get("primary_key")
    if not _str_list(pk):
        errors.append("primary_key tiene que ser una lista no vacía de columnas")
    else:
        for name in pk:
            if name not in by_name:
                errors.append(f"primary_key: la columna {name} no existe")
            elif by_name[name].get("nullable") is not False:
                errors.append(f"primary_key: la columna {name} no puede ser nulable")

    errors += _validate_geometry(data.get("geometry"), by_name)
    errors += _validate_count(data.get("count"), data.get("count_by"), by_name)
    errors += _validate_null_report(data.get("null_report"), by_name)
    return errors


def _validate_column(column: Any, index: int, names: list[str]) -> list[str]:
    if not isinstance(column, dict):
        return [f"columns[{index}] tiene que ser un mapeo"]
    name = column.get("name")
    where = f"columna {name or f'#{index}'}"
    errors = []
    if not isinstance(name, str) or not ENTITY.match(name):
        errors.append(f"{where}: nombre inválido")
    elif name in names:
        errors.append(f"{where}: nombre duplicado")
    else:
        names.append(name)
    type_ = column.get("type")
    if type_ not in TYPES:
        errors.append(f"{where}: tipo {type_!r} no es uno de {sorted(TYPES)}")
    if not isinstance(column.get("nullable"), bool):
        errors.append(f"{where}: nullable tiene que ser true o false")
    unknown = set(column) - {"name", "type", "nullable", "pattern", "allowed", "range"}
    if unknown:
        errors.append(f"{where}: claves desconocidas {sorted(unknown)}")
    if "pattern" in column:
        try:
            re.compile(column["pattern"])
        except (re.error, TypeError):
            errors.append(f"{where}: pattern no es una expresión regular válida")
        if type_ != "VARCHAR":
            errors.append(f"{where}: pattern solo aplica a VARCHAR")
    if "allowed" in column and not (isinstance(column["allowed"], list) and column["allowed"]):
        errors.append(f"{where}: allowed tiene que ser una lista no vacía")
    if "range" in column:
        bounds = column["range"]
        if type_ not in NUMERIC:
            errors.append(f"{where}: range solo aplica a columnas numéricas")
        elif not (
            isinstance(bounds, list)
            and len(bounds) == 2
            and all(_number(b) for b in bounds)
            and bounds[0] <= bounds[1]
        ):
            errors.append(f"{where}: range tiene que ser [mínimo, máximo]")
    return errors


def _validate_geometry(geometry: Any, by_name: dict[str, dict]) -> list[str]:
    if not isinstance(geometry, dict):
        return ["geometry tiene que ser un mapeo con types e inside_japan"]
    errors = []
    types = geometry.get("types")
    if not isinstance(types, list) or not set(types) <= GEOMETRY_TYPES:
        errors.append(f"geometry.types tiene que ser una lista de {sorted(GEOMETRY_TYPES)}")
        types = []
    if not isinstance(geometry.get("inside_japan"), bool):
        errors.append("geometry.inside_japan tiene que ser true o false")
    column = by_name.get(GEOMETRY_COLUMN)
    if types:
        if (
            column is None
            or column.get("type") != "GEOMETRY"
            or column.get("nullable") is not False
        ):
            errors.append("con geometry.types hace falta una columna geometry GEOMETRY no nulable")
    elif column is not None:
        errors.append("geometry.types está vacío pero hay una columna geometry")
    others = [n for n, c in by_name.items() if c.get("type") == "GEOMETRY" and n != GEOMETRY_COLUMN]
    if others:
        errors.append(f"la única columna GEOMETRY es geometry, no {others}")
    return errors


def _validate_count(count: Any, count_by: Any, by_name: dict[str, dict]) -> list[str]:
    errors = []
    if not isinstance(count, dict) or not _non_negative_int(count.get("min")):
        errors.append("count.min tiene que ser un entero >= 0")
    elif "max" in count and not (_non_negative_int(count["max"]) and count["max"] >= count["min"]):
        errors.append("count.max tiene que ser un entero >= count.min")
    if count_by is None:
        return errors
    if not isinstance(count_by, dict):
        return errors + ["count_by tiene que ser un mapeo con column y min"]
    column = by_name.get(count_by.get("column"))
    if column is None or "allowed" not in column:
        return errors + ["count_by.column tiene que ser una columna con allowed"]
    minimums = count_by.get("min")
    if not isinstance(minimums, dict) or not minimums:
        return errors + ["count_by.min tiene que ser un mapeo no vacío"]
    unknown = set(minimums) - set(column["allowed"])
    if unknown:
        errors.append(f"count_by.min tiene valores fuera de allowed: {sorted(unknown)}")
    if not all(_non_negative_int(v) for v in minimums.values()):
        errors.append("count_by.min tiene que tener enteros >= 0")
    return errors


def _validate_null_report(report: Any, by_name: dict[str, dict]) -> list[str]:
    if report is None:
        return []
    if not isinstance(report, dict) or not _str_list(report.get("columns")):
        return ["null_report.columns tiene que ser una lista no vacía"]
    errors = []
    for name in report["columns"]:
        if name not in by_name:
            errors.append(f"null_report: la columna {name} no existe")
        elif by_name[name].get("nullable") is not True:
            errors.append(f"null_report: la columna {name} no es nulable")
    by = report.get("by")
    if by is not None and by not in by_name:
        errors.append(f"null_report.by: la columna {by} no existe")
    return errors


def _build(data: dict[str, Any]) -> Contract:
    count_by = data.get("count_by") or {}
    report = data.get("null_report") or {}
    return Contract(
        entity=data["entity"],
        description=" ".join(data["description"].split()),
        sources=tuple(data["sources"]),
        primary_key=tuple(data["primary_key"]),
        geometry_types=tuple(data["geometry"]["types"]),
        inside_japan=data["geometry"]["inside_japan"],
        count_min=data["count"]["min"],
        count_max=data["count"].get("max"),
        count_by_column=count_by.get("column"),
        count_by_min=dict(count_by.get("min", {})),
        columns=tuple(
            Column(
                name=c["name"],
                type=c["type"],
                nullable=c["nullable"],
                pattern=c.get("pattern"),
                allowed=tuple(c["allowed"]) if "allowed" in c else None,
                range=tuple(c["range"]) if "range" in c else None,
            )
            for c in data["columns"]
        ),
        null_report_columns=tuple(report.get("columns", ())),
        null_report_by=report.get("by"),
    )


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _str_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(_nonempty_str(v) for v in value)


def _number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
