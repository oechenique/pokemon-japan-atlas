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
- Pipeline: `docker compose up -d` levanta Airflow 3 (LocalExecutor + Postgres) en http://localhost:8080, sin login. La imagen (`pipeline/Dockerfile`) trae DuckDB con `spatial` y `h3` preinstaladas. `atlas_smoke` es el DAG de humo del entorno.
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

**Fase 1 · Bronze: en curso.** Plan aprobado (2026-10-06): Overpass y Wikidata se consultan en cada corrida; en Fase 1 solo se crea el seed regiones del juego ↔ prefecturas, sin Bulbapedia como `source_url`; `fetched_at` y `checksum` van al `metadata.json` de cada corrida; `osm_buildings` alrededor del Pokémon Center Mega Tokyo.

- Pasos 1 y 2 hechos (verificación de licencias y de las Poké Lids), registrados en `pipeline/sources/LICENSES.md`.
- Decisiones aprobadas sobre el informe:
  - `viirs_night` pasa a NASA Black Marble VNP46A4 (CC0, 7 teselas de Japón) en lugar de EOG. Se publica solo la agregación H3. El token va en `.env` como `EARTHDATA_TOKEN`, lo crea el usuario y vence a los 60 días.
  - Copernicus GLO-90: los avisos y la exención de responsabilidad van en el footer, el manifest, los renders laterales y un `NOTICE` en la raíz.
  - Poké Lids: desde OSM, con cobertura declarada y sin fechas. Los aportes del día 16 tienen que venir de relevamiento propio, nunca del sitio oficial.
  - Overpass: consultas por bbox (no `area`), una sola instancia (`overpass-api.de`) y `osm_snapshot_date` fijado para la corrida final de publicación. Un `remark` de error cuenta como falla.

Pendiente para la Fase 2: deduplicar por id de OSM en Silver, porque las bbox de Overpass se solapan.
