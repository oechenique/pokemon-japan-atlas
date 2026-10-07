# 03 · Fuentes y pipeline

Esta regla define **qué datos entran**, **cómo fluyen** por el Medallion y **qué sale**. El catálogo de los 30 días está en `04-catalogo-30-dias.md`.

## Principio

**Todo sale del pipeline.** Hay dos tipos de salida y las dos se generan con el mismo DAG y el mismo `run_id`:

1. **Capas web**: lo que muestra el mapa único (PMTiles/GeoJSON).
2. **Renders laterales**: imágenes, PDFs o SVG para los días que no van en el front (ver regla 04). Se generan en `publish/<run_id>/side/`.

Si algo de la web o de un render no se puede rastrear hasta una tabla Gold y sus fuentes, está mal.

## Fuentes

Cada fuente se declara en `pipeline/sources/registry.yaml` con: `id`, `kind`, `url`, `license`, `attribution`, `fetched_at`, `checksum` y las capas que alimenta. **Agregar una fuente es agregar una entrada al registro más su módulo**; nunca se descarga nada que no esté registrado.

| id | Fuente | Licencia | Qué aporta | Estado |
|---|---|---|---|---|
| `natural_earth` | Natural Earth (admin-1, costas, ciudades, batimetría, áreas urbanas) | Dominio público | Mapa base, prefecturas, polígonos de región, agua | ✅ |
| `osm_overpass` | OpenStreetMap vía Overpass API, consultas acotadas a Japón por categoría | ODbL | Pokémon Centers, tiendas y cafés Pokémon, onsen, centrales eléctricas, estaciones, Shinkansen | ✅ |
| `osm_buildings` | OpenStreetMap, edificios de un área chica alrededor de un solo punto | ODbL | Día borgeano (zoom a escala de edificio) | ✅ |
| `wikidata` | Wikidata SPARQL | CC0 | Nombres en ja/en/es, regiones reales, datos factuales | ✅ |
| `pokeapi` | PokeAPI (**solo datos**, nunca imágenes) | Datos factuales | Generaciones, regiones del juego, años | ✅ |
| `kontur_population` | Kontur Population, recorte de Japón (hexágonos H3 de 400 m) | CC BY 4.0 | Urbano/rural y densidad | ✅ verificada 2026-10-06 |
| `viirs_night` | NASA Black Marble VNP46A4 (luces nocturnas VIIRS anuales), 7 teselas de Japón | CC0 (política de datos de NASA); requiere `EARTHDATA_TOKEN` | Luz y oscuridad | ✅ verificada 2026-10-06 (reemplaza a EOG) |
| `copernicus_dem` | Copernicus DEM GLO-90 (bucket público en AWS Open Data) | Licencia GLO-90 Full, Free & Open: avisos y exención de responsabilidad obligatorios (ver `NOTICE`) | Cuenca visual del Fuji, raster | ✅ verificada 2026-10-06 |
| `seeds` | CSVs curados a mano en `pipeline/seeds/` | Propia; cada fila lleva su URL de fuente | Correspondencias región/ciudad del juego ↔ real, datos sin fuente abierta | ✅ |

Reglas de fuentes:
- **⚠️ = verificar la licencia vigente en la Fase 1 antes de descargar.** Si no está clara: no se usa y se pregunta (regla 00).
- **Poké Lids** (tapas de alcantarilla): no hay fuente abierta confirmada. Orden de búsqueda: OSM → Wikidata → seed curado con URL oficial por fila (solo ubicación y fecha, como hechos). **Si solo existe el sitio oficial, se pregunta antes de usarlo.**
- **Overpass**: User-Agent propio con contacto, una consulta por categoría y por bbox (nunca `area`), pausa entre consultas, timeout explícito y respeto de la política de uso del servicio. Se usa una sola instancia. Un `remark` de error en la respuesta cuenta como falla, aunque venga con HTTP 200. La corrida final de publicación fija `[date:"..."]` para que el snapshot de OSM sea reproducible. Las respuestas crudas se guardan en Bronze: nunca se consulta dos veces lo mismo en una corrida.
- **Poké Lids**: se toman de OSM (verificado en la Fase 1: unas 260 de más de 370), con la cobertura declarada y sin fechas.
- **Wikidata**: User-Agent propio (lo pide su política) y consultas chicas.
- **Rasters (VIIRS, DEM)**: **nunca se baja el archivo global.**
  - DEM: se lee solo la ventana de Japón vía `/vsis3/` sobre los COG, y se guarda ese recorte.
  - VIIRS (Black Marble): se bajan solo las teselas HDF5 de 10° que cubren Japón, se recortan y se guarda el recorte, no la tesela.
- **Seeds**: cada fila tiene `source_url`. Las correspondencias juego ↔ realidad se marcan con `confidence` (`oficial`, `ampliamente aceptada` o `teoría de fans`) y la web lo muestra.

## Flujo

```
registry.yaml
     │
     ▼
BRONZE  data/bronze/<source>/run_id=<id>/   crudo + checksum + metadata.json
     │   idempotente: si el checksum coincide con la corrida anterior, no re-descarga
     ▼
SILVER  data/silver/<entidad>.parquet      (GeoParquet)
     │   esquema normalizado, EPSG:4326, geometrías válidas,
     │   h3_r7/h3_r9, prefectura, región del juego, licencia por fila
     ▼
DQ GATE  pipeline/quality/                → publish/<run_id>/quality_report.json
     │   si falla un check bloqueante: no hay Gold ni publicación
     ▼
GOLD    data/gold/<entidad>.parquet + vistas gold.v_day_XX
     │
     ├──► PUBLISH  publish/<run_id>/web/   PMTiles, GeoJSON, content JSON
     ├──► SIDE     publish/<run_id>/side/  PNG, SVG, PDF de los días laterales
     └──► manifest.json                    fuentes, licencias, artefactos, hashes, linaje
```

## Esquemas Silver (contratos)

Cada entidad tiene su contrato en `pipeline/contracts/<entidad>.yaml`: columnas, tipos, nulabilidad y checks. Entidades mínimas:

| Entidad | Geometría | Columnas clave |
|---|---|---|
| `poi` | Point | `poi_id`, `source`, `source_id`, `category`, `name_ja`, `name_en`, `name_es`, `prefecture_code`, `game_region`, `h3_r9`, `license` |
| `rail` | LineString | `rail_id`, `kind` (shinkansen, línea), `name_*`, `license` |
| `station` | Point | `station_id`, `name_*`, `lines`, `h3_r9` |
| `prefecture` | MultiPolygon | `prefecture_code`, `name_*`, `real_region` |
| `game_region` | MultiPolygon | `region_id`, `game_name`, `real_region`, `generation`, `year`, `confidence` |
| `h3_metric` | celda H3 | `h3`, `resolution`, `metric` (population, night_light, poi_density), `value` |
| `raster_product` | COG | `product_id`, `kind` (viewshed, hillshade), `bbox`, `path` |

## Data Quality gate

**Bloqueantes** (si fallan, no se publica):
- Geometrías válidas y no vacías.
- Todo punto cae dentro del bbox de Japón (salvo la capa "fuera de Japón").
- Claves primarias únicas.
- Toda fila tiene `license`.
- Conteos mínimos por entidad, definidos en el contrato (por ejemplo, `game_region` = 4).

**Informativos** (se reportan, no bloquean):
- Tasa de nulos por columna y por prefectura (por ejemplo, POIs sin `name_en`).
- Variación de conteos contra la corrida anterior.

El `quality_report.json` se publica: **es el insumo del día 18 (NULL)**.

## Orquestación (Airflow 3)

- **Un DAG principal, `atlas_run`**, con un `run_id` único generado al inicio y pasado a todas las tareas.
  - TaskGroup `bronze`: **mapeo dinámico** sobre las fuentes de `registry.yaml` (una tarea por fuente).
  - TaskGroup `silver`: una tarea por entidad (SQL de DuckDB en `pipeline/transforms/`).
  - `dq_gate`.
  - TaskGroup `gold`.
  - `publish_web`, `publish_side` (en paralelo) y `write_manifest`.
- Cada tarea declara sus **Assets** (entradas y salidas) para que el linaje se vea en la UI de Airflow.
- Reintentos con backoff en las tareas de red. Las de transformación no reintentan: si fallan, es un bug.
- **Idempotencia**: correr `atlas_run` dos veces con las mismas fuentes produce los mismos artefactos (mismos hashes, salvo timestamps de metadata).

## Herramientas de procesamiento

- **DuckDB** (`spatial`, `h3`) para todo lo vectorial y tabular.
- **GDAL/rasterio** para rasters (recorte, cuenca visual con `gdal_viewshed`, hillshade). Los rasters que van a la web **se agregan a H3** y se publican como vector: el front nunca carga rasters.
- **tippecanoe o `pmtiles`** para generar PMTiles. El mapa base también se genera acá (Natural Earth → PMTiles).
- **matplotlib + cartopy** para los renders laterales, usando **los mismos tokens** de `web/tokens/` (exportados a JSON en el build) para que los PNG tengan la misma identidad visual que la web.

## Comandos

Todo con `make` (o `just`), documentado en el `CLAUDE.md`:
- `make up` / `make down`: levantar o bajar el stack.
- `make run`: disparar `atlas_run`.
- `make test`: tests del pipeline.
- `make publish-check`: valida el manifest y los tamaños.

## Alcance por fase

| Fase | Qué cubre de esta regla |
|---|---|
| 1 · Bronze | `registry.yaml`, verificación de licencias ⚠️, ingesta de **todas** las fuentes con checksum e idempotencia |
| 2 · Silver/Gold | Contratos, transformaciones, H3, agregación de rasters, DQ gate, vistas `v_day_XX` |
| 3 · Publicación | PMTiles (incluido el mapa base), GeoJSON, content JSON, renders laterales, manifest |
