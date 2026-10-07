"""Carga y validación del registro de fuentes (pipeline/sources/registry.yaml, reglas/03).

El registro es la única puerta de entrada de datos: si una fuente no está acá, no se
descarga. La validación junta todos los errores de una vez para que un registro roto
se arregle en una sola pasada.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SOURCES_DIR = Path(__file__).resolve().parent
REGISTRY_PATH = SOURCES_DIR / "registry.yaml"

# Las fuentes que exige reglas/03.
REQUIRED_SOURCE_IDS = frozenset(
    {
        "natural_earth",
        "osm_overpass",
        "osm_buildings",
        "wikidata",
        "pokeapi",
        "kontur_population",
        "viirs_night",
        "copernicus_dem",
        "seeds",
    }
)

# PokeAPI solo para datos factuales: nunca recursos con sprites o artwork (reglas/00).
POKEAPI_ALLOWED_RESOURCES = frozenset({"generation", "region"})

# Entidades Silver de reglas/03, más el mapa base y los edificios del día 14.
ENTITIES = frozenset(
    {
        "poi",
        "rail",
        "station",
        "prefecture",
        "game_region",
        "h3_metric",
        "raster_product",
        "building",
        "basemap",
    }
)

# Parámetros obligatorios de cada tipo de fuente.
KIND_PARAMS: dict[str, frozenset[str]] = {
    "http_files": frozenset({"files"}),
    "overpass": frozenset({"categories"}),
    "overpass_around": frozenset({"center", "radius_m", "selectors", "out"}),
    "sparql": frozenset({"queries"}),
    "rest_json": frozenset({"resources"}),
    "cog_tiles": frozenset({"bucket", "region", "tile_name", "aois"}),
    "earthdata_tiles": frozenset(
        {
            "product",
            "collection",
            "year",
            "archive_url",
            "token_env",
            "tiles",
            "crop_bbox",
            "layers",
        }
    ),
    "local_csv": frozenset({"dir", "files"}),
}

OVERPASS_OUT = frozenset({"center", "geom"})
# Un selector de Overpass sin bbox ni área: tipo de elemento y filtros de tags.
# Al no admitir paréntesis, deja afuera `(area...)`.
OVERPASS_SELECTOR = re.compile(r"^(node|way|relation|nwr)(\[[^\]\[]+\])+$")
SNAPSHOT_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SOURCE_ID = re.compile(r"^[a-z][a-z0-9_]*$")
BLACK_MARBLE_TILE = re.compile(r"^h\d{2}v\d{2}$")
ENV_VAR = re.compile(r"^[A-Z][A-Z0-9_]*$")

# Límites generosos alrededor de Japón para atrapar bboxes con lat/lon invertidas.
JAPAN_EXTENT = (20.0, 122.0, 46.0, 154.0)  # sur, oeste, norte, este
# osm_buildings es un "área chica alrededor de un solo punto" (reglas/03).
MAX_AROUND_RADIUS_M = 2000


class RegistryError(ValueError):
    """El registro no cumple el esquema."""


@dataclass(frozen=True)
class Source:
    id: str
    kind: str
    url: str
    license: dict[str, str]
    attribution: str
    feeds: tuple[str, ...]
    days: tuple[int, ...]
    params: dict[str, Any]


@dataclass(frozen=True)
class Registry:
    user_agent: str
    overpass: dict[str, Any]
    japan_bboxes: dict[str, tuple[float, float, float, float]]
    sources: tuple[Source, ...]

    def get(self, source_id: str) -> Source:
        for source in self.sources:
            if source.id == source_id:
                return source
        raise KeyError(source_id)

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(source.id for source in self.sources)


def load_raw(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_registry(path: Path = REGISTRY_PATH) -> Registry:
    data = load_raw(path)
    errors = validate(data, base_dir=path.parent)
    if errors:
        raise RegistryError("registry.yaml inválido:\n- " + "\n- ".join(errors))
    return Registry(
        user_agent=data["user_agent"],
        overpass=dict(data["overpass"]),
        japan_bboxes={name: tuple(bbox) for name, bbox in data["japan_bboxes"].items()},
        sources=tuple(
            Source(
                id=s["id"],
                kind=s["kind"],
                url=s["url"],
                license=dict(s["license"]),
                attribution=s["attribution"].strip(),
                feeds=tuple(s["feeds"]),
                days=tuple(s["days"]),
                params=s["params"],
            )
            for s in data["sources"]
        ),
    )


def validate(data: Any, base_dir: Path = SOURCES_DIR) -> list[str]:
    """Devuelve la lista de errores del registro; vacía si es válido."""
    if not isinstance(data, dict):
        return ["el registro tiene que ser un mapeo YAML"]
    errors: list[str] = []

    if data.get("version") != 1:
        errors.append("version tiene que ser 1")
    user_agent = data.get("user_agent")
    if not _nonempty_str(user_agent) or not ("+http" in user_agent or "@" in user_agent):
        errors.append("user_agent tiene que incluir un contacto (URL con + o email)")

    errors += _validate_overpass(data.get("overpass"))

    bboxes = data.get("japan_bboxes")
    if not isinstance(bboxes, dict) or not bboxes:
        errors.append("japan_bboxes tiene que ser un mapeo no vacío")
        bboxes = {}
    for name, bbox in bboxes.items():
        errors += _validate_bbox(bbox, f"japan_bboxes.{name}")

    sources = data.get("sources")
    if not isinstance(sources, list) or not sources:
        return errors + ["sources tiene que ser una lista no vacía"]

    seen: set[str] = set()
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            errors.append(f"sources[{index}] tiene que ser un mapeo")
            continue
        source_id = source.get("id")
        where = f"fuente {source_id or f'#{index}'}"
        if not isinstance(source_id, str) or not SOURCE_ID.match(source_id):
            errors.append(f"{where}: id inválido")
        elif source_id in seen:
            errors.append(f"{where}: id duplicado")
        else:
            seen.add(source_id)
        errors += _validate_source(source, where, set(bboxes), base_dir)

    missing = REQUIRED_SOURCE_IDS - seen
    if missing:
        errors.append(f"faltan fuentes exigidas por reglas/03: {sorted(missing)}")
    return errors


def _validate_overpass(overpass: Any) -> list[str]:
    if not isinstance(overpass, dict):
        return ["overpass tiene que ser un mapeo"]
    errors = []
    if not _is_https(overpass.get("endpoint")):
        errors.append("overpass.endpoint tiene que ser una URL https")
    if not _positive_int(overpass.get("timeout_s")):
        errors.append("overpass.timeout_s tiene que ser un entero positivo")
    if not _positive_int(overpass.get("pause_s")):
        errors.append("overpass.pause_s tiene que ser un entero positivo")
    snapshot = overpass.get("snapshot_date", "falta")
    if snapshot is not None and not (isinstance(snapshot, str) and SNAPSHOT_DATE.match(snapshot)):
        errors.append(
            "overpass.snapshot_date tiene que ser null o una fecha UTC AAAA-MM-DDThh:mm:ssZ"
        )
    return errors


def _validate_source(
    source: dict[str, Any], where: str, bbox_names: set[str], base_dir: Path
) -> list[str]:
    errors = []
    kind = source.get("kind")
    if kind not in KIND_PARAMS:
        errors.append(f"{where}: kind desconocido {kind!r}")
    if not _is_https(source.get("url")):
        errors.append(f"{where}: url tiene que ser https")

    license_ = source.get("license")
    if not isinstance(license_, dict) or not all(
        _nonempty_str(license_.get(key)) for key in ("id", "name", "url")
    ):
        errors.append(f"{where}: license necesita id, name y url")
    elif not _is_https(license_["url"]):
        errors.append(f"{where}: license.url tiene que ser https")
    if not _nonempty_str(source.get("attribution")):
        errors.append(f"{where}: falta attribution")

    feeds = source.get("feeds")
    if not isinstance(feeds, list) or not feeds or not set(feeds) <= ENTITIES:
        errors.append(f"{where}: feeds tiene que ser una lista no vacía de {sorted(ENTITIES)}")
    days = source.get("days")
    if (
        not isinstance(days, list)
        or not days
        or not all(isinstance(d, int) and 1 <= d <= 30 for d in days)
    ):
        errors.append(f"{where}: days tiene que ser una lista no vacía de días 1 a 30")

    params = source.get("params")
    if not isinstance(params, dict):
        return errors + [f"{where}: params tiene que ser un mapeo"]
    if kind in KIND_PARAMS:
        missing = KIND_PARAMS[kind] - params.keys()
        if missing:
            return errors + [f"{where}: faltan params {sorted(missing)}"]
        errors += _KIND_CHECKS[kind](params, where, bbox_names, base_dir)
    return errors


def _check_http_files(params, where, _bbox_names, _base_dir) -> list[str]:
    files = params["files"]
    if not isinstance(files, list) or not files:
        return [f"{where}: files tiene que ser una lista no vacía"]
    errors = []
    names = [f.get("name") for f in files if isinstance(f, dict)]
    if len(names) != len(files) or not all(_nonempty_str(n) for n in names):
        errors.append(f"{where}: cada archivo necesita name")
    elif len(set(names)) != len(names):
        errors.append(f"{where}: nombres de archivo duplicados")
    for f in files:
        if isinstance(f, dict) and not _is_https(f.get("url")):
            errors.append(f"{where}: archivo {f.get('name')} sin url https")
    return errors


def _check_overpass(params, where, bbox_names, _base_dir) -> list[str]:
    categories = params["categories"]
    if not isinstance(categories, list) or not categories:
        return [f"{where}: categories tiene que ser una lista no vacía"]
    errors = []
    seen: set[str] = set()
    for category in categories:
        cid = category.get("id") if isinstance(category, dict) else None
        if not isinstance(cid, str) or not SOURCE_ID.match(cid):
            errors.append(f"{where}: categoría sin id válido")
            continue
        if cid in seen:
            errors.append(f"{where}: categoría {cid} duplicada")
        seen.add(cid)
        errors += _check_selectors(category.get("selectors"), f"{where}.{cid}")
        if category.get("out") not in OVERPASS_OUT:
            errors.append(f"{where}.{cid}: out tiene que ser uno de {sorted(OVERPASS_OUT)}")
        boxes = category.get("bboxes")
        if boxes != "all" and not (isinstance(boxes, list) and boxes and set(boxes) <= bbox_names):
            errors.append(f"{where}.{cid}: bboxes tiene que ser 'all' o nombres de japan_bboxes")
    return errors


def _check_overpass_around(params, where, _bbox_names, _base_dir) -> list[str]:
    errors = []
    center = params["center"]
    if not isinstance(center, dict) or not _inside_japan(center.get("lat"), center.get("lon")):
        errors.append(f"{where}: center necesita lat/lon dentro de Japón")
    radius = params["radius_m"]
    if not _positive_int(radius) or radius > MAX_AROUND_RADIUS_M:
        errors.append(f"{where}: radius_m tiene que ser un entero entre 1 y {MAX_AROUND_RADIUS_M}")
    errors += _check_selectors(params["selectors"], where)
    if params["out"] not in OVERPASS_OUT:
        errors.append(f"{where}: out tiene que ser uno de {sorted(OVERPASS_OUT)}")
    return errors


def _check_sparql(params, where, _bbox_names, base_dir) -> list[str]:
    queries = params["queries"]
    if not isinstance(queries, list) or not queries:
        return [f"{where}: queries tiene que ser una lista no vacía"]
    errors = []
    for query in queries:
        if not isinstance(query, dict) or not _nonempty_str(query.get("id")):
            errors.append(f"{where}: cada consulta necesita id")
            continue
        path = base_dir / str(query.get("file", ""))
        if not query.get("file") or not path.is_file():
            errors.append(f"{where}: no existe el archivo de la consulta {query['id']}")
    return errors


def _check_rest_json(params, where, _bbox_names, _base_dir) -> list[str]:
    resources = params["resources"]
    if not isinstance(resources, list) or not resources:
        return [f"{where}: resources tiene que ser una lista no vacía"]
    forbidden = set(resources) - POKEAPI_ALLOWED_RESOURCES
    if forbidden:
        return [f"{where}: recursos no permitidos {sorted(forbidden)} (solo datos factuales)"]
    return []


def _check_cog_tiles(params, where, _bbox_names, _base_dir) -> list[str]:
    errors = []
    tile_name = params["tile_name"]
    if not isinstance(tile_name, str) or "{lat}" not in tile_name or "{lon}" not in tile_name:
        errors.append(f"{where}: tile_name tiene que tener {{lat}} y {{lon}}")
    aois = params["aois"]
    if not isinstance(aois, dict) or not aois:
        return errors + [f"{where}: aois tiene que ser un mapeo no vacío"]
    for name, bbox in aois.items():
        errors += _validate_bbox(bbox, f"{where}.aois.{name}")
    return errors


def _check_earthdata_tiles(params, where, _bbox_names, _base_dir) -> list[str]:
    errors = []
    if not isinstance(params["year"], int):
        errors.append(f"{where}: year tiene que ser un entero")
    if not _is_https(params["archive_url"]) or "{year}" not in params["archive_url"]:
        errors.append(f"{where}: archive_url tiene que ser https y tener {{year}}")
    if not isinstance(params["token_env"], str) or not ENV_VAR.match(params["token_env"]):
        errors.append(f"{where}: token_env tiene que ser un nombre de variable de entorno")
    tiles = params["tiles"]
    if (
        not isinstance(tiles, list)
        or not tiles
        or not all(isinstance(t, str) and BLACK_MARBLE_TILE.match(t) for t in tiles)
    ):
        errors.append(f"{where}: tiles tiene que ser una lista de teselas hXXvYY")
    layers = params["layers"]
    if not isinstance(layers, list) or not layers or not all(_nonempty_str(x) for x in layers):
        errors.append(f"{where}: layers tiene que ser una lista no vacía de capas del HDF5")
    errors += _validate_bbox(params["crop_bbox"], f"{where}.crop_bbox")
    return errors


def _check_local_csv(params, where, _bbox_names, _base_dir) -> list[str]:
    files = params["files"]
    if not isinstance(files, list) or not files:
        return [f"{where}: files tiene que ser una lista no vacía"]
    errors = []
    for f in files:
        if (
            not isinstance(f, dict)
            or not _nonempty_str(f.get("name"))
            or not _nonempty_str(f.get("file"))
        ):
            errors.append(f"{where}: cada seed necesita name y file")
            continue
        columns = f.get("required_columns")
        if not isinstance(columns, list) or "source_url" not in columns:
            errors.append(f"{where}: el seed {f['name']} tiene que exigir la columna source_url")
    return errors


_KIND_CHECKS = {
    "http_files": _check_http_files,
    "overpass": _check_overpass,
    "overpass_around": _check_overpass_around,
    "sparql": _check_sparql,
    "rest_json": _check_rest_json,
    "cog_tiles": _check_cog_tiles,
    "earthdata_tiles": _check_earthdata_tiles,
    "local_csv": _check_local_csv,
}


def _check_selectors(selectors: Any, where: str) -> list[str]:
    if not isinstance(selectors, list) or not selectors:
        return [f"{where}: selectors tiene que ser una lista no vacía"]
    return [
        f"{where}: selector inválido {s!r} (solo tipo y filtros de tags, sin área ni bbox)"
        for s in selectors
        if not isinstance(s, str) or not OVERPASS_SELECTOR.match(s)
    ]


def _validate_bbox(bbox: Any, where: str) -> list[str]:
    if not (
        isinstance(bbox, list)
        and len(bbox) == 4
        and all(isinstance(v, int | float) and not isinstance(v, bool) for v in bbox)
    ):
        return [f"{where}: bbox tiene que ser [sur, oeste, norte, este]"]
    south, west, north, east = bbox
    if not (south < north and west < east):
        return [f"{where}: bbox con sur >= norte u oeste >= este"]
    if not (_inside_japan(south, west) and _inside_japan(north, east)):
        return [f"{where}: bbox fuera de los límites de Japón {JAPAN_EXTENT}"]
    return []


def _inside_japan(lat: Any, lon: Any) -> bool:
    if not all(isinstance(v, int | float) and not isinstance(v, bool) for v in (lat, lon)):
        return False
    south, west, north, east = JAPAN_EXTENT
    return south <= lat <= north and west <= lon <= east


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_https(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("https://")


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
