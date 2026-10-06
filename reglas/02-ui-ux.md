# 02 · UI / UX

Referencia de principios: `referencias/platanus/ANALISIS.md`. Se toman **principios**, no código, assets ni textos.

## Idea central

Una pantalla, un protagonista. El mapa es lo único que se mueve solo. El resto (wordmark, lista de regiones, controles) es chico, plano y quieto. **La lista y el mapa son un solo sistema**: la lista navega, el mapa muestra, y la lista es además la alternativa accesible del mapa.

## Layout

**Desktop (≥ 768 px)**: grid de 2 columnas.
```
┌────────────────────────────────────────────────┐
│ pokemon japan atlas [30]          [ES|EN] [☀|☾] │
│ KANTO · JOHTO · HOENN · SINNOH                   │
├──────────────────────────┬─────────────────────┤
│                          │ [tarjeta Kanto ●]   │
│   MAPA (globo → Japón)   │ [tarjeta Johto]     │
│                          │ [tarjeta Hoenn]     │
│                          │ [tarjeta Sinnoh]    │
│                          │ [tarjeta apagada]   │
│                          │ ── panel detalle ── │
├──────────────────────────┴─────────────────────┤
│ ◄ AIRFLOW · DUCKDB · H3 · POKEAPI · OSM … ►     │
└────────────────────────────────────────────────┘
```

**Mobile (< 768 px)**: el mapa ocupa la parte superior (`flex: 1`) y la lista va en un **bottom sheet** con tres alturas (cerrado, mitad y completo) y scroll propio.

Reglas de altura:
- El contenedor del mapa usa `100dvh`.
- **El panel de la derecha y el bottom sheet tienen scroll interno.** Nunca uses `overflow: hidden` sobre contenido navegable: nada puede quedar cortado en pantallas bajas.

## Componentes

### Wordmark
`pokemon japan atlas [30]` en Dela Gothic One. Los corchetes y el `30` van en `--accent`. Debajo, el subtítulo en DotGothic16 con tracking amplio.

### Tarjetas de región
Son bloques sólidos: fondo `--ink`, texto `--ink-inverse`. Esa inversión es la señal de que se pueden tocar.

| Región | Línea 2 (JA + real) | Línea 3 |
|---|---|---|
| KANTO | 関東 · Kantō | Gen I · 1996 |
| JOHTO | 関西 · Kansai | Gen II · 1999 |
| HOENN | 九州 · Kyūshū | Gen III · 2002 |
| SINNOH | 北海道 · Hokkaidō | Gen IV · 2006 |
| FUERA DE JAPÓN | Unova · Kalos · Alola · Galar · Paldea | Gen V+ · 2010 |

- **Kanto lleva el pulso** (`--dur-pulse`): es la única tarjeta animada, porque ahí empezó todo.
- **La tarjeta "Fuera de Japón"** va en estado apagado (fondo `--ink-15`, borde `--ink-35`, texto `--ink-80`). En hover, el globo **se aleja a una vista global** que muestra esas regiones como puntos tenues (EE. UU., Francia, Hawái, Reino Unido, Península Ibérica), pero no tiene panel de detalle. Lleva `aria-disabled`.
- Hover: `scale(1.01)` y nada más. El feedback real lo da el mapa.

### Panel de detalle
Aparece al seleccionar una región. Muestra un texto corto que cuenta qué la inspiró, contadores (puntos y capas) y los chips de las capas disponibles: **Puntos → Líneas → Polígonos**, que se van revelando en ese orden. El rojo marca la capa activa.

### Controles
Idioma `ES|EN` y tema `☀|☾`, chicos, en la esquina superior derecha. Se persisten en `localStorage` (con `try/catch`). El estado inicial sale de `navigator.language` y de `prefers-color-scheme`, y un script inline lo aplica antes de pintar para evitar el flash.

### Cinta inferior
Un marquee con el stack y las fuentes de datos, con los bordes fundidos por `mask-image`. Se pausa fuera del viewport y con la pestaña oculta. Con reduced-motion queda estático.

## Interacciones

| Acción | Desktop | Mobile |
|---|---|---|
| Explorar región | Hover o focus en la tarjeta: `flyTo` y polígono | Primer toque: `flyTo`, polígono y ficha resumida |
| Abrir detalle | Click en la tarjeta | Segundo toque o botón "Ver más" |
| Volver | Esc o botón ← | Botón ← o deslizar el sheet hacia abajo |
| Click en un punto del mapa | Resalta el ítem en el panel y abre su popup | Igual, con la ficha en el sheet |

- **Intención antes de volar**: el hover espera 250 ms antes de disparar `flyTo`. Si el puntero sale antes, no vuela. Así, recorrer las cinco tarjetas con el mouse no encadena cinco vuelos.
- **Hover explora, selección confirma**: el hover mueve el mapa pero no toca la URL. Solo el click o el toque de selección actualizan la URL.
- Teclado: las tarjetas son enfocables, y focus dispara lo mismo que hover. Tab sigue el orden visual.
- Mientras el usuario interactúa, **la rotación idle se pausa**. Se reanuda 8 s después de la última interacción, y solo si la vista es el globo.

## Coreografía

1. **Entrada**: la página llega pintada (export estático). Después hay un reveal escalonado: wordmark, mapa, tarjetas con `--stagger` y cinta. Opacidad de 0 a 1 y `translateY` de 10 px a 0, con `--dur-reveal`.
2. **Mapa**: el contenedor arranca en opacidad 0 y hace fade cuando MapLibre emite `load`. Nunca se ve un canvas vacío.
3. **Idle**: el globo gira lento **desplazando la longitud del centro** (no el bearing, que solo gira la vista sobre el eje de la pantalla), alrededor de 60 s por vuelta, medido por tiempo y no por frames.
4. **Selección**: `flyTo` a la región con `--dur-fly`, transición de globo a mercator al pasar zoom 5, y el polígono aparece con fade de `--dur-base`.
5. **Capas**: puntos, líneas y polígonos aparecen con fade, nunca de golpe.

## Estados por URL

- `?region=kanto` abre la región seleccionada.
- `?day=4` abre el estado del día 4 del challenge (región, capas y cámara definidos en `web/content/days.json`).
- `?lang=en` y `?theme=night` tienen prioridad sobre `localStorage`.
- Cada selección actualiza la URL con `history.replaceState`, así cualquier vista se puede compartir. El hover nunca la toca.

## Accesibilidad

- `<html lang>` dinámico (`es` o `en`), y el texto japonés con `lang="ja"`.
- **No se bloquea el zoom**: nada de `maximum-scale=1`.
- La lista de regiones y el panel contienen toda la información del mapa, así que el canvas lleva `aria-hidden` y un `aria-label` descriptivo en su contenedor.
- Contraste mínimo de 4.5:1 en texto y de 3:1 en componentes (ver tokens).
- Foco visible: outline de 2 px en `--accent`, con offset de 2 px.
- `prefers-reduced-motion` se respeta **también en el mapa y en la cinta**.

## Performance

- JS inicial de menos de 300 KB comprimido. MapLibre se carga con `import()` diferido, después del primer pintado.
- Los datos geográficos van siempre en archivos aparte (PMTiles o GeoJSON), **nunca embebidos en el JS**.
- Las animaciones propias se pausan con `visibilitychange` y `IntersectionObserver`.
- Las fuentes, en WOFF2 con subset (ver tokens).
- Objetivo: Lighthouse de 90 o más en Performance y Accessibility, tanto en mobile como en desktop.

## Extra

- Publicar `/llms.txt` con la lista de regiones, capas y fuentes en texto plano.
- El footer lleva atribuciones (© OpenStreetMap contributors, Natural Earth, PokeAPI) y el disclaimer de proyecto de fans.
