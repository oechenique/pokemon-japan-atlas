# pokemon-japan-atlas

Web de **un solo mapa interactivo** (MapLibre, globo → Japón) que cuenta el Japón detrás de 30 años de Pokémon (1996–2026). La alimenta un **pipeline de datos reproducible**: Airflow + DuckDB en Medallion, publicado como PMTiles/GeoJSON con `manifest.json`. Ese mismo pipeline resuelve el #30DayMapChallenge de noviembre de 2026. Es bilingüe EN/ES, con modo día/noche, para web y mobile.

## Fuente de verdad

Las reglas de `reglas/` mandan sobre cualquier otra cosa, incluido este archivo:

- `reglas/00-vision-y-alcance.md`: principios no negociables, stack, estructura, contrato pipeline → web y fases.
- `reglas/01-design-tokens.md`: color, tipografía, espaciado, movimiento y estilo del mapa.
- `reglas/02-ui-ux.md`: layout, componentes, interacciones, accesibilidad y performance.

**Antes de empezar cada fase, leé completas las tres reglas.** Antes de tocar `web/`, releé siempre la 01 y la 02.

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
