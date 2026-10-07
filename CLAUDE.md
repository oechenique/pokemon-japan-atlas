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

Propuesta, sin implementar: partir Overpass en una tarea por consulta. La segunda corrida tardó 49 min, a 11 del `execution_timeout` de 1 h.

- `osm_overpass` deja de ser una sola tarea. Un `@task` arma la lista de consultas (categoría × bbox, hoy 50) desde el registro, y `fetch_query` se expande sobre esa lista con `map_index_template` = `<categoría>/<bbox>`. Cada consulta tiene su propio `execution_timeout` (unos 5 min) y sus reintentos con backoff.
- Concurrencia 1 con un pool `overpass` de 1 slot, compartido con `osm_buildings`. Es mejor que `max_active_tis_per_dag`, que limita una sola tarea. El lock de archivo y `pause_s` quedan como respaldo.
- Una tarea final `finish_overpass` junta los resultados y escribe el `metadata.json` de la fuente. Para eso, `BronzeRun.finish()` tiene que poder llamarse aparte de la ingesta. El `_progress.jsonl` ya sirve como punto de encuentro entre tareas.
- El TaskGroup `bronze` queda con el mapeo por fuente para las otras 7 y un sub-grupo `overpass`.
