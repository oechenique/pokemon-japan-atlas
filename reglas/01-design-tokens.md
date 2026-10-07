# 01 · Design tokens

Toda la UI **y el estilo del mapa** salen de estos tokens. Ningún color, fuente ni duración se escribe a mano en un componente.

## Principio: dos tintas por modo

Cada modo tiene una tinta de fondo y una de texto. Todos los estados (secundario, deshabilitado, bordes) se derivan con **opacidad del color de texto**, no con colores nuevos. El rojo es el único acento y se reserva para lo seleccionado o activo.

## Color

| Token | Día (washi) | Noche (farol) | Uso |
|---|---|---|---|
| `--bg` | `#F4EFE6` papel washi | `#0F1A2E` índigo | Fondo de página |
| `--ink` | `#1A1A1A` sumi | `#FFD27A` luz de farol | Texto, tarjetas sólidas, íconos |
| `--ink-inverse` | `#F4EFE6` | `#0F1A2E` | Texto sobre tarjetas sólidas (inversión) |
| `--accent` | `#E3350D` rojo Pokébola | `#E3350D` | Selección, región activa, marcador activo |
| `--ink-80` | `--ink` al 80% | ídem | Texto secundario |
| `--ink-35` | `--ink` al 35% | ídem | Bordes, separadores |
| `--ink-15` | `--ink` al 15% | ídem | Fondo de estados deshabilitados |

Reglas:
- **El rojo nunca se usa para texto chico.** Sobre washi da 3.8:1 y sobre índigo 4.0:1. Alcanza para componentes de UI y texto grande (3:1), pero no para texto de cuerpo. Usalo para rellenos, bordes, marcadores y polígonos activos. Sobre superficies claras de noche queda justo en 3:1: evitá esa combinación.
- **Texto deshabilitado = `--ink-80`.** Al 60% no llega a 4.5:1 (sobre washi da 4.4 y sobre la tarjeta apagada, menos de 4.2). El estado apagado se comunica con el fondo `--ink-15` y el borde `--ink-35`, no atenuando el texto.
- **Los contrastes los vigila un test** (Vitest, corre en CI): cada par de texto debe dar al menos 4.5:1 y cada par de componente, 3:1, en día y en noche.
- `color-scheme` se sincroniza con el tema visible (`light` en día, `dark` en noche).
- `::selection` invierte: fondo `--ink`, texto `--bg`.

### Easter egg: Game Boy

Se activa con el código Konami (↑ ↑ ↓ ↓ ← → ← → B A). Reemplaza toda la paleta por los 4 verdes del Game Boy original y se desactiva repitiendo el código o recargando la página.

| Token | Valor |
|---|---|
| `--bg` | `#9BBC0F` |
| `--ink` | `#0F380F` |
| `--ink-inverse` | `#9BBC0F` |
| `--accent` | `#306230` |
| (tono extra) | `#8BAC0F` para rellenos de polígonos |

**Excepción documentada**: el modo Game Boy queda fuera del test de contraste, porque es un easter egg temporal que se activa a propósito. Aun así, todo texto va en `--ink` sobre `--bg` (6.0:1), sin opacidades, y el acento nunca se usa para texto.

## Tipografía

| Rol | Familia | Uso | Desktop | Mobile | Tracking |
|---|---|---|---|---|---|
| Wordmark | **Dela Gothic One** | Solo `pokemon japan atlas [30]` | 64 px | 32 px | `-0.03em` |
| Labels | **DotGothic16** | Nombres de región, subtítulos y botones, siempre en MAYÚSCULAS | 18 px | 12 px | `0.08em` (subtítulo: `0.18em`) |
| Datos | **M PLUS 1 Code** | Años, generación, coordenadas, contadores y cuerpo | 14–16 px | 12–13 px | normal |

- Las tres familias tienen glifos japoneses, así que kana y kanji se ven con la misma voz que el texto latino.
- **Self-hosting en WOFF2.** Nada de Google Fonts en runtime.
- **Subsetting**: el latín es completo, pero el japonés se reduce a los glifos que usa el contenido. Se genera en el build a partir de los textos de `web/content/` y se carga con `unicode-range` separado. **Hasta la Fase 4 se carga solo el latín** más el fallback del sistema.
- Cargá solo los pesos que se usan (400 en las tres; 700 en M PLUS 1 Code para fechas).
- `font-display: swap`. Fallback: `system-ui, "Hiragino Sans", "Yu Gothic", sans-serif`.
- Los textos en japonés van envueltos en `lang="ja"`.

## Implementación

- Los tokens viven en **un único archivo fuente** (`web/tokens/tokens.ts`). De ahí se generan las variables CSS, el tema de Tailwind y, desde la Fase 4, los estilos del mapa.
- Tailwind v4 expone solo los tokens a través de `@theme`. **Se desactiva la paleta por defecto de Tailwind** y no se permiten valores arbitrarios de color (`bg-[#...]`). Si un color no es un token, no existe.

## Espaciado y forma

- Escala de espaciado: `4 · 8 · 12 · 16 · 24 · 32 · 48 · 64` px.
- Padding lateral de página: 16 px en mobile y 32 px en desktop. Ancho máximo de 1400 px.
- **Bordes rectos** (`border-radius: 0`) en todo, coherente con la fuente pixel.
- Breakpoint único: **768 px**.

## Movimiento

| Token | Valor | Uso |
|---|---|---|
| `--ease-out` | `cubic-bezier(.22, 1, .36, 1)` | Entradas y vuelos de cámara |
| `--ease-standard` | `cubic-bezier(.4, 0, .2, 1)` | Hover y cambios de estado |
| `--dur-fast` | `150ms` | Hover |
| `--dur-base` | `400ms` | Cambios de panel y fades de capas |
| `--dur-fade` | `400ms` (150ms con reduced-motion) | Fades de opacidad |
| `--dur-reveal` | `700ms` | Entrada escalonada |
| `--stagger` | `120ms` | Retraso entre ítems de una lista |
| `--dur-fly` | `1600ms` | `flyTo` de MapLibre |
| `--dur-pulse` | `2200ms` | Pulso de la tarjeta destacada |

Con `prefers-reduced-motion: reduce`, todas las duraciones pasan a `0ms`, salvo los fades de opacidad, que quedan en `150ms`. En el mapa, `flyTo` se reemplaza por `jumpTo`, y se apagan la rotación idle y el pulso.

## Estilo del mapa

- Hay dos estilos JSON de MapLibre, día y noche, generados en el build a partir de **estos mismos tokens**. Ningún color del mapa se escribe a mano.
- El mapa base es casi monocromo: tierra en `--ink` al 8%, agua en `--bg`, límites en `--ink-35`, sin rutas salvo en los estados que las necesiten.
- Puntos de interés en `--ink`. El activo o seleccionado va en `--accent`.
- Polígono de región: relleno `--accent` al 20% y borde `--accent` de 2 px.
- Etiquetas del mapa con `["coalesce", ["get", "name:es"], ["get", "name"]]` según el idioma, y el nombre japonés como etiqueta secundaria cuando exista.
- `pixelRatio` limitado a `Math.min(devicePixelRatio, 2)`.
