# 00 · Visión y alcance — pokemon-japan-atlas

## Qué es

Una web de **un solo mapa interactivo** que cuenta el Japón detrás de 30 años de Pokémon (1996–2026), alimentada por **un pipeline de datos reproducible**. Ese mismo pipeline resuelve las consignas del #30DayMapChallenge 2026 (del 1 al 30 de noviembre).

Lema: **"30 años, 30 días, 1 pipeline"** · 一日一地図

## Principios no negociables

1. **Reproducible y sin licencias pagas.** Todo corre en local con `docker compose up`. En la nube solo viven la web estática y sus artefactos.
2. **Una sola corrida.** La web muestra un snapshot congelado, identificado por `run_id`. No es un sistema vivo.
3. **Un solo mapa.** Hay una única instancia de MapLibre que cambia de estado. Nunca hay varios mapas en la página.
4. **Datos abiertos, licencias limpias.**
   - Prohibido: datos de Niantic (PokéStops y gyms de Pokémon GO), Bulbapedia (CC BY-NC-SA), logos oficiales de Pokémon o Nintendo, y **cualquier artwork o sprite de Pokémon, aunque venga vía PokeAPI**. PokeAPI no relicencia las imágenes: siguen siendo © Nintendo/Creatures/GAME FREAK. Este proyecto es sobre lugares y no necesita imágenes de personajes.
   - Permitido:
     - Natural Earth (dominio público): mapa base, costas y prefecturas.
     - OpenStreetMap (ODbL): puntos de interés. Lleva atribución, y la base derivada se comparte bajo la misma licencia (el repo es público, así que se cumple). Se registra en el manifest.
     - PokeAPI, **solo para datos factuales** (nombres, generaciones, regiones).
     - Listados oficiales públicos usados como hechos (direcciones, fechas).
   - Toda fuente nueva se registra en `manifest.json` con su licencia. **Si la licencia de una fuente no está clara, no se usa: hay que preguntar.**
   - El footer incluye un disclaimer de proyecto de fans sin fines comerciales.
5. **Bilingüe EN/ES, modo día/noche, web y mobile desde el día 1.** Nada de "después lo adaptamos".

## Stack

| Capa | Tecnología |
|---|---|
| Orquestación | Airflow en Docker Compose |
| Procesamiento | DuckDB con las extensiones `spatial` y `h3`, en Medallion (Bronze/Silver/Gold) sobre GeoParquet |
| Calidad | Data Quality gate entre Silver y Gold: si falla, no se publica |
| Publicación | PMTiles (vectorial), GeoJSON chico para capas livianas y JSON de contenido |
| Mapa base | PMTiles propios generados desde Natural Earth. Sin proveedor externo de tiles |
| Front | Next.js con export estático, Tailwind v4 (mapeado a los tokens), MapLibre GL JS v5 con proyección `globe` |
| Hosting | Vercel (web y artefactos). Cloudflare R2 solo si hace falta (ver contrato) |
| IaC | Terraform: proyecto de Vercel (y R2 solo si se activa), providers oficiales, state local |
| CI | GitHub Actions desde la Fase 0: lint, tests, contraste de tokens, `terraform validate` y, desde la Fase 3, validación del manifest |

## Entorno

- El repo vive en `C:\dev\pokemon-japan-atlas`, **fuera de OneDrive**.
- Docker Desktop con backend WSL2 y al menos 4 GB de RAM asignados (Airflow los necesita).
- Git desde el día 1, con un repo **público** en GitHub: la idea es que se pueda forkear.

## Estructura del repo

```
pokemon-japan-atlas/
├── reglas/                 # estas reglas
├── docker-compose.yml      # Airflow + volúmenes
├── pipeline/
│   ├── dags/
│   ├── sources/            # un módulo por fuente
│   ├── transforms/         # bronze → silver → gold (SQL DuckDB)
│   ├── quality/            # checks del DQ gate
│   └── tests/
├── data/                   # gitignored: bronze/ silver/ gold/
├── publish/<run_id>/       # artefactos exportados + manifest.json
├── web/                    # Next.js
├── infra/                  # Terraform
└── referencias/            # análisis de diseño (no se publica)
```

## Contrato pipeline → web

- La web solo consume `publish/<run_id>/`. **Nunca llama a APIs externas en runtime, sin excepciones**: el mapa base también es un artefacto propio.
- `manifest.json` incluye: `run_id`, fecha de la corrida, fuentes con su licencia y la URL de origen, lista de artefactos con su hash y tamaño, y el mapeo de capa → tabla Gold.
- Por defecto, todo se sirve desde Vercel. R2 se activa solo si algún artefacto no entra cómodo en el deploy, y **se pregunta antes**, porque requiere tarjeta registrada y conviene un dominio propio en Cloudflare.

## Web y challenge

- Estados direccionables por URL: `?region=kanto`, `?day=4`.
- El mapeo día → estado del mapa vive en `web/content/days.json` (se define en una fase posterior).
- Algunos días se resuelven fuera del DAG y se documentan así: 7 (*10 minute map*), 10 (*Prompting only*), 16 (*Collaborative map*) y 30 (*Pen & paper*).

## Fases

| Fase | Entregable |
|---|---|
| 0 · Esqueleto | Repo con git, Docker Compose con Airflow, Next.js + Tailwind v4 con los tokens (fuentes solo en latín), Terraform base (providers fijados, sin recursos ni credenciales) y CI |
| 1 · Bronze | Ingesta de todas las fuentes, idempotente, con `run_id` |
| 2 · Silver/Gold | Limpieza, geometrías válidas, H3, DQ gate |
| 3 · Publicación | Export a PMTiles/GeoJSON y `manifest.json` |
| 4 · Front base | Shell, wordmark, tarjetas de regiones, mapa globo → Japón y subset japonés de las fuentes |
| 5 · Estados | Capas por día, panel de detalle, i18n y temas completos |
| 6 · Deploy | Terraform (Vercel; R2 solo si se activó), README, capturas y video |

**Deadline:** pipeline y front base (fases 0 a 4) listos antes del **1/11/2026**.

## Cómo trabajar (para Claude Code)

- Una fase por vez. No adelantes trabajo de fases futuras.
- Al cerrar cada fase: tests en verde, commit con mensaje claro y un resumen corto de lo hecho y lo pendiente.
- Leé siempre `01-design-tokens.md` y `02-ui-ux.md` antes de tocar `web/`.
- Ante una duda de licencia, de alcance o de diseño que no esté en estas reglas: preguntá antes de decidir.
