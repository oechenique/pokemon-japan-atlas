# pokemon-japan-atlas

Web de **un solo mapa interactivo** (MapLibre, globo → Japón) que cuenta el Japón detrás de 30 años de Pokémon (1996–2026). La alimenta un **pipeline de datos reproducible**: Airflow + DuckDB en Medallion, publicado como PMTiles/GeoJSON con `manifest.json`. Ese mismo pipeline resuelve el #30DayMapChallenge de noviembre de 2026. Es bilingüe EN/ES, con modo día/noche, para web y mobile.

## Fuente de verdad

Las reglas de `reglas/` mandan sobre cualquier otra cosa, incluido este archivo:

- `reglas/00-vision-y-alcance.md`: principios no negociables, stack, estructura, contrato pipeline → web y fases.
- `reglas/01-design-tokens.md`: color, tipografía, espaciado, movimiento y estilo del mapa.
- `reglas/02-ui-ux.md`: layout, componentes, interacciones, accesibilidad y performance.
- `reglas/03-fuentes-y-pipeline.md`: fuentes y licencias, flujo Medallion, contratos Silver, DQ gate y orquestación.
- `reglas/04-catalogo-30-dias.md`: qué resuelve cada día del challenge y si va en la web o como render lateral.

**Antes de empezar cada fase, leé completas las cinco reglas.** Antes de tocar `web/`, releé siempre la 01 y la 02.

## Forma de trabajo

- Una fase por vez. No adelantes trabajo de fases futuras.
- Al cerrar una fase: tests en verde, commit con mensaje claro y un resumen corto de lo hecho y lo pendiente.
- Ante una duda de licencia, alcance o diseño que las reglas no resuelvan: preguntá antes de decidir.
- `referencias/` es solo análisis de diseño: se toman principios, nunca código, assets ni textos. No se publica. Sus capturas de terceros quedan fuera de git.

## Entorno y comandos

- El repo vive en `C:\dev\pokemon-japan-atlas`, fuera de OneDrive. Node 24 (`.nvmrc`).
- `web/` usa Next.js 16, que cambia APIs respecto de versiones anteriores: seguí `web/AGENTS.md` y consultá la documentación incluida en `web/node_modules/next/dist/docs/` antes de escribir código de Next.
- Los tokens salen solo de `web/tokens/tokens.ts`. `npm run tokens` regenera `web/app/tokens.css` (no se edita a mano) y `npm run fonts` copia las fuentes a `web/public/fonts/`.
- Verificación de `web/`: `npm run lint && npm run typecheck && npm test && npm run build && npm run check:export`.
- Pipeline: `docker compose up -d` levanta Airflow 3 (LocalExecutor + Postgres) en http://localhost:8080, sin login. La imagen (`pipeline/Dockerfile`) trae DuckDB con `spatial` y `h3` preinstaladas. `atlas_smoke` es el DAG de humo del entorno. `atlas_run` se dispara con `docker compose exec airflow-scheduler airflow dags trigger atlas_run`; el informe de cada corrida queda en `data/bronze/_runs/`.
- Verificación de `pipeline/` (desde Git Bash, `MSYS_NO_PATHCONV=1` evita que reescriba la ruta): `docker compose run --rm --no-deps -e CONNECTION_CHECK_MAX_COUNT=0 -w /opt/airflow/pipeline airflow-scheduler bash -c "ruff check . && ruff format --check . && pytest"`.
- CI falla si algún archivo de `publish/` supera 10 MiB.
- Verificación de `infra/`: `terraform fmt -check && terraform init -backend=false && terraform validate`.

## Estado actual

**Fase 0 · Esqueleto: cerrada** (2026-10-06).

- Commits: `f184800` (esqueleto, web con tokens, infra base) y `e4b0c3d` (Airflow en Docker Compose, job de pipeline y tope de `publish/`).
- CI en verde en GitHub (web, infra, pipeline, publish-size): corrida `37547428649`.
- Repo público: https://github.com/oechenique/pokemon-japan-atlas (lo creó Claude Code con `gh`; no existía).

Decisiones de esta sesión:

- Airflow 3.3.2 (imagen slim + driver de Postgres) con LocalExecutor y Postgres 17. Sin triggerer ni Celery para ahorrar RAM; se suman si un DAG los necesita.
- UI de Airflow sin login (SimpleAuthManager, todos admin), expuesta solo en `127.0.0.1:8080`. Credenciales de desarrollo local, no se despliegan.
- DuckDB 1.5.6 con `spatial` y `h3` (repositorio community) instaladas al construir la imagen, para no bajarlas en cada corrida.
- Una sola imagen para correr y verificar el pipeline (ruff y pytest incluidos).
- Tope de `publish/`: 10 MiB (10.485.760 bytes) por archivo, controlado en CI.

**Reglas nuevas recibidas (2026-10-06):** `reglas/03-fuentes-y-pipeline.md` (fuentes, Medallion, contratos, DQ gate, DAG `atlas_run`) y `reglas/04-catalogo-30-dias.md` (catálogo de los 30 días: web o render lateral). Ajustes en la 00 (todos los días salen del pipeline; fases 1 a 3 redefinidas) y en la 01 (token `--dur-fade`, pendiente de llevar a `web/tokens/tokens.ts`).

**Fase 1 · Bronze: cerrada** (2026-10-07).

- Commit: `d64d6ca`. CI en verde (web, infra, pipeline, publish-size): corrida `37637810819`.

Qué quedó:

- Registro de las 9 fuentes (`pipeline/sources/registry.yaml`), licencias verificadas (`pipeline/sources/LICENSES.md`), `NOTICE` y `.env.example`.
- Base común de ingesta (`pipeline/sources/base.py`):
  - escribe en `data/bronze/<source>/run_id=<id>/` con escritura atómica y un `metadata.json` por fuente (`fetched_at`, checksum por archivo y del conjunto, licencia, avisos);
  - descargas condicionales por ETag; lo que no cambió se enlaza (hardlink) desde la corrida anterior;
  - reanuda los reintentos sin repetir consultas.
- Un módulo por fuente en `pipeline/sources/<id>.py`. Overpass comparte `_overpass.py`. Un test controla que registro y módulos coincidan.
- Seed `pipeline/seeds/game_regions.csv`: 25 filas (Kanto, Johto, Hoenn, Sinnoh ↔ prefecturas), fuente Wikidata P144 y `confidence = ampliamente aceptada`. Johto = Kansai + Tōkai (Aichi, Gifu, Shizuoka), no todo Chūbu.
- DAG `atlas_run` con `start_run` y el TaskGroup `bronze` (mapeo dinámico por fuente, reintentos con backoff e informe en `data/bronze/_runs/`). El run_id viaja como `atlas_run_id`, porque `run_id` está reservado en Airflow.
- Imagen con rasterio 1.5.2 (GDAL 3.12.2), h5py, numpy y requests, más `pip check`.
- 107 tests.

Corridas de `atlas_run`:

| run_id | Modo | Duración | Resultado |
|---|---|---|---|
| `20261007T125201Z` | query | 34 min | Primera ingesta: 94 archivos, 314,6 MB. |
| `20261007T133653Z` | query | 49 min | 8 de 9 fuentes con checksum idéntico, Overpass incluido. VIIRS difería solo por el `mtime` del directorio en `listing.json`; se corrigió: ahora pasa a `metadata.json`. |
| `20261007T143142Z` | reuse | 30 s | Overpass sin consultas (51 archivos reusados). El listado de VIIRS cambió una vez por el formato nuevo y después se verificó estable. |

Bronze por corrida (MB): `copernicus_dem` 130,3 · `osm_overpass` 99,0 · `natural_earth` 60,9 · `kontur_population` 16,1 · `viirs_night` 6,9 · `osm_buildings` 1,2 · `pokeapi` 0,27 · `wikidata` 0,03 · `seeds` 0,003. Con hardlinks, las tres corridas ocupan 397 MB en `data/bronze/`.

Decisiones de la Fase 1 (también reflejadas en las reglas 03 y 04):

- `viirs_night` pasa a NASA Black Marble VNP46A4 (CC0) en lugar de EOG, con 8 teselas: el 2026-10-07 se sumó h32v06 para cubrir Ogasawara. Se guardan dos capas recortadas (`AllAngle_Composite_Snow_Free` y `_Quality`) y se publica solo la agregación H3. El token va en `.env`, lo crea el usuario y vence a los 60 días (el actual, el 2026-12-06). Si falta o venció y hay corrida anterior, se reusa el recorte entero con un aviso; si no la hay, falla.
- Copernicus GLO-90: los avisos y la exención de responsabilidad van en el footer, el manifest, los renders laterales y el `NOTICE`.
- Poké Lids: desde OSM, con cobertura declarada y sin fechas. Los aportes del día 16 tienen que venir de relevamiento propio, nunca del sitio oficial.
- Overpass:
  - consultas por bbox (no `area`) a una sola instancia (`overpass-api.de`), con `overpass.snapshot_date` fijado para la corrida final de publicación;
  - un `remark` de error cuenta como falla, aunque venga con HTTP 200;
  - `timestamp_osm_base` pasa a `metadata.json`, para que el checksum dependa solo de los datos.
- `OVERPASS_MODE` en `.env`: `query` (default) o `reuse`, que copia el último Bronze sin consultar si las consultas no cambiaron, y lo marca en `metadata.json` (`extra.overpass_mode`, `warnings`, `reused_from`). Es solo para desarrollo.

Pendiente para la Fase 2:

- Deduplicar por id de OSM en Silver, porque las bbox de Overpass se solapan.
- VIIRS: el producto trae píxeles de relleno en islas chicas (25% alrededor de Chichijima). Tratarlos como nulos al agregar a H3.

Pendiente para la Fase 3:

- La publicación tiene que fallar si algún Bronze de la corrida tiene `extra.overpass_mode = reuse` (o, en general, archivos de Overpass con `reused_from`), para que nunca se publique por accidente un snapshot reusado.

La partición de Overpass que se había propuesto acá se implementó en el paso 1 de la Fase 2.

**Fase 2 · Silver/Gold: en curso. Pasos 1 a 4 cerrados (2026-10-07); próximo: paso 5 (rasters y H3), con `OVERPASS_MODE=reuse`.**

Plan aprobado (2026-10-07):

1. Partir Overpass.
2. Contratos.
3. Silver base (`prefecture`, `game_region`).
4. Silver vectorial (`poi`, `rail`, `station`, `building`, con deduplicación por id de OSM).
5. Rasters y H3.
6. DQ gate y `quality_report.json`.
7. Gold y `v_day_XX`.
8. DAG, idempotencia y una sola corrida final con `query`.

Paso 1 · Overpass partido (corrida `20261007T145530Z`, con `query`):

- `overpass_queries` arma el plan de consultas (58: 57 de `osm_overpass` y 1 de `osm_buildings`).
- `fetch_query` corre una tarea por consulta, en el pool `overpass` de 1 slot que crea `airflow-init`, con un timeout de 10 min y 3 reintentos.
- `finish_overpass` cierra las dos fuentes y falla si falta un archivo del plan o sobra uno.
- La corrida tardó 64 min en total, sin reintentos. Cada consulta tardó entre 32 s y 3 min 4 s, con mediana de 66 s, contra un timeout de 10 min.
- Las 50 consultas que ya existían dieron el mismo checksum que en la corrida `20261007T133653Z`. El listado de VIIRS quedó estable también en una corrida real.

Bronze nuevo:

- Categoría `pokemon_store`: 9 tiendas en OSM.
- Consulta de Wikidata `game_regions_based_on` (`P144` y coordenadas): da Unova, Kalos y Alola.
- Seeds:
  - `regions_outside_japan.csv`: Galar, `oficial` (entrevista de pokemon.com, 2019, archivada en la Wayback Machine porque el original da 404), y Paldea, `ampliamente aceptada` con Wikipedia (no se encontró una declaración oficial).
  - `game_places.csv`: 40 lugares, 6 `ampliamente aceptada` y 34 `teoría de fans`. Las fuentes son Wikidata `P144`, un tuit de Masuda y prensa (TheGamer, GameRant y CBR). Nunca wikis de fans.
    - `ampliamente aceptada` exige fuentes de **dos grupos editoriales distintos**. TheGamer, GameRant y CBR son de Valnet y cuentan como uno.
    - La columna `source_groups` lleva los grupos de cada fila. El validador (`seeds.PUBLISHER_GROUPS`) la calcula a partir de los dominios citados y falla si un dominio no tiene grupo asignado.
  - `pokemon_cafes.csv`: los dos Pokémon Café, con la dirección de la web oficial (`shop.pokemon.co.jp`) como hecho y las coordenadas del nodo de OSM. Entran a `poi` con `source = seed`, y el nodo de OSM citado no se duplica.
- `game_regions.csv`: las filas de Kantō, Kansai, Kyūshū y Hokkaidō pasan a `oficial` con la entrevista "社長が訊く" de Nintendo (2010). Las de Tōkai siguen como `ampliamente aceptada`.
- Regla 04: el día 23 queda con los dos Pokémon Café. Wikidata tiene 55 platos regionales con prefectura, en 34 de 47 prefecturas y ninguno en Hokkaidō (Sinnoh quedaría vacía), así que no alcanza.
- El día 8 arranca a nivel región, con la fuente oficial, y suma las ciudades encima. La web muestra el `confidence` de cada una.

Insumos para el día 18 (NULL):

- Wikidata `P144`: solo 5 de los 158 lugares del juego de las cuatro regiones japonesas lo tienen, ninguno con referencia. Galar y Paldea tampoco lo tienen.
- OSM: de los dos Pokémon Café, solo el de Tokio tiene `brand`. El de Osaka (nodo 7012998620) está solo por nombre.
- Wikidata, platos regionales: no hay ninguno con prefectura en 13 prefecturas, entre ellas Hokkaidō.

Paso 2 · Contratos:

- 11 contratos en `pipeline/contracts/<entidad>.yaml`: las 7 de la regla 03 más `building`, `basemap`, `game_place` y `outside_region`.
- Cada contrato fija columnas, tipos, nulabilidad, `pattern`, `allowed` y `range`; la clave primaria; el tipo de geometría y si va dentro de Japón; los conteos (`count`, `count_by`), y qué nulos se reportan (`null_report`).
- El validador está en `pipeline/quality/contracts.py`. Exige `license` no nulable en todas las entidades y controla que contratos y `feeds` del registro coincidan en los dos sentidos.
- Mínimos por categoría: alrededor del 80% de Bronze al 2026-10-07. En Bronze hay 22 Pokémon Center, 9 Pokémon Store, 257 Poké Lids, 1022 onsen y 19885 centrales.
- Pokémon Café: en OSM, solo uno tiene `brand`, así que los dos entran por el seed (mínimo 2).

Paso 3 · Silver base (corrida `20261007T174238Z`, con `reuse`):

- Base de transformación en `pipeline/transforms/base.py`:
  - lee Bronze de una sola corrida y solo de fuentes completas;
  - escribe `data/silver/<entidad>.parquet` con las columnas, el orden y los tipos del contrato (CAST explícito), ordenado por la clave primaria;
  - la geometría queda etiquetada como `OGC:CRS84`, que es EPSG:4326 en orden lon/lat;
  - controla el esquema escrito contra el contrato.
- El `run_id` no va dentro del parquet, para que el hash no cambie entre corridas. El linaje queda en `data/silver/_runs/`.
- `atlas_run` suma el grupo `silver`: una tarea por entidad (`silver_entities.DEPENDENCIES`) sin reintentos, con el Bronze de su contrato como inlets, más `lineage`.
- Entidades:
  - `prefecture` (47): Natural Earth más nombres de Wikidata. Saga y Nagasaki toman la región del seed `prefecture_regions.csv`, porque ni Natural Earth ni Wikidata (`P361`) la traen.
  - `game_region` (4): unión de prefecturas. Su `confidence` es la más baja entre sus filas, así que Johto queda `ampliamente aceptada`.
  - `game_place` (40).
  - `outside_region` (5): generación de PokeAPI y año desde la consulta nueva `generation_games` (fecha de los primeros juegos, solo fechas reales).
- `regions_outside_japan.csv` pasa a tener las 5 regiones, con fuente y `source_groups` por fila. Wikidata `P144` queda de respaldo: una región que falte en el seed entra como `teoría de fans`.
  - Unova: `oficial` (Masuda en "社長が訊く": ニューヨークをモチーフにしました).
  - Kalos y Alola: `oficial`, con declaraciones de los desarrolladores relatadas o reproducidas por Siliconera (presentación de la Japan Expo 2013 y entrevista de Nintendo of Europe de 2016).
  - Galar: `oficial` (pokemon.com, archivado).
  - Paldea: `ampliamente aceptada`. Wikipedia, Polygon y Kotaku, leídas y confirmadas. Polygon cuenta como Valnet, su dueño desde 2025.

Paso 4 · Silver vectorial (corrida `20261007T180708Z`, con `reuse`):

- `pipeline/transforms/osm.py`: lee Overpass como JSON y deduplica por id de OSM.
  - Si un elemento aparece en varias categorías, gana la de mayor precedencia.
  - Cuenta los descartes: los repetidos por bbox solapadas y los que caen en más de una categoría.
  - Prefectura de cada punto: `within`, o `nearest` a menos de 0,05° (unos 5 km); si no, NULL.
- Entidades:
  - `poi` (21 196):
    - 21 Pokémon Center, 9 Store, 2 Café, 257 Poké Lids, 1022 onsen y 19 885 centrales.
    - Center y Store se separan por el nombre, porque en OSM hay errores de marca: se reclasificaron 3.
    - Los dos cafés salen del seed, y el nodo de OSM que cita el seed no se duplica.
  - `rail` (47 195): 13 101 vías de Shinkansen (6338 km) y 34 094 de la red de Kanto. Ante un duplicado gana `shinkansen`.
  - `station` (9091): solo 4 tienen `lines`.
  - `building` (1745): 41 con altura y 237 con cantidad de pisos. Los multipolígonos se arman como outer menos inner.
- DuckDB:
  - cada conexión tiene un tope de 2 GB y 2 hilos, y vuelca a disco en `data/_tmp/duckdb`;
  - `maximum_object_size` se ajusta al archivo más grande que se lee (un valor fijo grande agotaba la memoria);
  - pool `duckdb` de 2 slots para las tareas de Silver.

Insumos para el día 18 (NULL), del paso 4:

- 30 POIs sin prefectura: 7 en las Kuriles del sur (administradas por Rusia, dentro de la bbox de Hokkaidō), 9 en islas del sur como Tokara, y el resto en islas chicas que Natural Earth a 10 m no tiene.
- Errores de marca en OSM entre Pokémon Center y Store: 3.
- Estaciones con `lines`: 4 de 9091.

