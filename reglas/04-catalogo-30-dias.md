# 04 · Catálogo de los 30 días

Consignas oficiales del #30DayMapChallenge 2026 (1 al 30 de noviembre), resueltas con **un solo pipeline**.

- **Web**: es un estado del mapa único (`?day=N`), con cámara, capas y texto definidos en `web/content/days.json`.
- **Lateral**: render generado por el pipeline en `publish/<run_id>/side/`. No va en el mapa, pero sí en la web como galería de "días laterales", con link al render y a su tabla Gold.

Las correspondencias juego ↔ realidad salen de `seeds` con su nivel de `confidence`. **Ninguna se presenta como oficial si no lo es.**

## Catálogo

| Día | Consigna | Idea | Gold / fuentes | Dónde |
|---|---|---|---|---|
| 1 | Points | Pokémon Centers de Japón (y Poké Lids, si hay fuente válida) | `poi` (osm, seeds) | Web |
| 2 | Lines | Red ferroviaria de Kanto con el Shinkansen destacado | `rail` (osm) | Web |
| 3 | Polygons | Las 4 regiones del juego sobre sus prefecturas reales | `game_region`, `prefecture` (natural_earth, seeds) | Web |
| 4 | Clusters | Dónde se amontona lo Pokémon: clusters de tiendas y cafés en Tokio y Osaka | `poi` + clustering | Web |
| 5 | Senses: Sight | Desde dónde se ve el Fuji: cuenca visual calculada sobre el DEM | `raster_product` → polígono (copernicus_dem) | Web |
| 6 | Vintage | Todo el atlas en paleta Game Boy (el easter egg, activado por URL) | Todas las capas | Web |
| 7 | 10 minute map | Con el Gold listo, un mapa armado en 10 minutos cronometrados (se documenta el tiempo) | Cualquier vista Gold | Lateral |
| 8 | Utopia | Si el mundo Pokémon fuera real: ciudades del juego en sus inspiraciones reales | seeds (`confidence` visible) | Web |
| 9 | Urban-rural | Población en hexágonos H3 por región del juego | `h3_metric` population (kontur) | Web |
| 10 | Prompting only | Un LLM que solo lee `llms.txt` y los GeoJSON publicados arma un mapa de punta a punta; se publica el prompt | Artefactos publicados | Lateral |
| 11 | Senses: Sound | Dónde se escucha el Shinkansen: buffer de las vías como proxy (declarado como proxy) | `rail` + H3 | Web |
| 12 | Power | Centrales eléctricas reales en el Kanto de la Central de Energía del juego | `poi` power (osm) | Web |
| 13 | Interactions | Cada Pokémon Center y su estación más cercana: filtros interactivos | `poi`, `station` | Web |
| 14 | Borgesian map | Zoom a escala de edificio alrededor de un Pokémon Center: el mapa se vuelve territorio | `osm_buildings` | Web |
| 15 | Inside out | Sinnoh dado vuelta (Hokkaidō con el sur arriba), guiño al Mundo Distorsión | `game_region` + cámara con bearing 180° | Web |
| 16 | Collaborative map | Puntos aportados por la comunidad vía PR al seed, validados por el DQ en CI | `seeds` comunitarios | Lateral (los datos aprobados entran a la web) |
| 17 | Light & dark | Luces nocturnas de Japón agregadas a H3, más los temas día/noche | `h3_metric` night_light (viirs) | Web |
| 18 | NULL | Mapa de los huecos: tasas de nulos por prefectura según el `quality_report.json` | DQ report | Lateral |
| 19 | Senses: Smell | Onsen de Japón: el olor a azufre, con foco en Kyūshū (Hoenn) | `poi` onsen (osm) | Web |
| 20 | Hexagons | Densidad de puntos Pokémon en H3 | `h3_metric` poi_density | Web |
| 21 | OpenStreetMap | Todo lo del atlas que viene de OSM, con conteos y atribución | Capas con `source = osm` | Web |
| 22 | Projections | La transición globo → mercator en el front, más un render lateral de Japón en varias proyecciones | `prefecture` | Web + lateral |
| 23 | Senses: Taste | Pokémon Cafés y comida típica por región | `poi` food (osm, seeds) | Web |
| 24 | Network | Grafo del Shinkansen que conecta las ciudades con Pokémon Center | `rail`, `station`, `poi` | Web |
| 25 | Is this a map? | El DAG de Airflow dibujado como un mapa de región: el linaje como territorio | `manifest.json` (linaje) | Web (panel) + lateral |
| 26 | Water | Los mares de Hoenn: batimetría y costas de Kyūshū | natural_earth (batimetría) | Web |
| 27 | New tool | El stack como herramienta nueva: DuckDB + H3 + PMTiles + MapLibre globe, explicado en el panel | Todas | Web |
| 28 | Senses: Feeling | Nostalgia: 30 años, región por región, de Kanto 1996 a hoy | `game_region` (años) | Web |
| 29 | Raster | Relieve sombreado de las 4 regiones desde el DEM | `raster_product` hillshade | Lateral |
| 30 | Pen & paper | El pipeline imprime un PDF lienzo (contornos de las regiones y grilla) para dibujar el mapa a mano; se publica la foto del resultado | `game_region` | Lateral |

## Notas

- **Días laterales**: 7, 10, 16, 18, 29 y 30 (más el render extra del 22 y el 25). Igual salen del pipeline y quedan en el manifest.
- **Días que dependen de una fuente ⚠️** (5, 9, 17, 29): si la licencia no se confirma en la Fase 1, se replantean con otra fuente antes de la Fase 2.
- **Día 1**: si no aparece fuente válida para las Poké Lids, el día queda solo con Pokémon Centers.
- **Día 16**: requiere un `CONTRIBUTING.md` y una plantilla de PR para el seed. Se arma en la Fase 5. Los aportes tienen que venir de **relevamiento propio** (visita o foto propia, con fecha); **nunca del sitio oficial de Pokémon**, ni copiados de otras bases. El `CONTRIBUTING.md` lo tiene que decir explícitamente.
- El texto de cada día (ES/EN) vive en `web/content/days.json` y se escribe en la Fase 5.
