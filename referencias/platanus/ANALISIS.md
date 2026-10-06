# Análisis de referencia: hack.platan.us

> Fecha: 2026-10-06 · Página analizada: home (`/`) · Método: lectura de HTML/CSS/JS (descargados a una carpeta temporal, **no** al repo), capturas con Playwright (Chromium headless) y recorrido en vivo con Chrome.
> Este documento describe y razona; no contiene código, assets ni textos del sitio.

Capturas en [`capturas/`](capturas/):

| Archivo | Qué muestra |
|---|---|
| `desktop-1440-01-reveal-250ms.png` | Entrada escalonada a mitad de camino (las tarjetas de abajo todavía están apareciendo) |
| `desktop-1440-02-cargada.png` | Estado final en desktop |
| `desktop-1440-03-hover-mexico.png` | Hover sobre una ciudad: el globo gira hasta centrarla |
| `desktop-1440-04-hover-santiago-deshabilitado.png` | Hover sobre la tarjeta deshabilitada |
| `desktop-1440-05-tras-scroll.png` | Después de scrollear: no cambia nada, la página no tiene scroll |
| `desktop-1440-06-foco-teclado.png` | Navegación con Tab |
| `desktop-1440-reduced-motion-*.png` | Con `prefers-reduced-motion: reduce` |
| `mobile-390-01/02/03/04*.png` | Mobile (iPhone 13 emulado): entrada, cargada, tras scroll y tap |
| `mobile-390-reveal-{150,500,1600}ms.png` | Ráfaga de la secuencia de entrada en mobile |

---

## 0. Stack técnico

| Capa | Qué usa |
|---|---|
| Backend | Ruby on Rails (cookie de sesión de Rails y token CSRF) detrás de Cloudflare |
| Puente | **Inertia.js**: el servidor manda el componente y sus props como JSON embebido en el HTML |
| UI | **React** con **SSR**: el HTML llega ya renderizado y después se hidrata |
| Build | Vite con Rolldown (bundles con hash bajo `/vite/assets/`) |
| CSS | **Tailwind CSS v4.3** con tokens shadcn (`--background`, `--primary`, … en HSL) |
| Tema | `next-themes` (script inline anti-flash y clase `dark` en `<html>`) |
| 3D | **three.js** + **three-globe** (globo de hexágonos), cargado con `import()` diferido. `@react-three/fiber` también está en el bundle, pero el globo de la home usa three directo, no R3F |
| Otros en el bundle | recharts, sonner (toasts), i18next y Leaflet (en un chunk `map` diferido), todo para otras páginas |
| Animación | **Ninguna librería** (ni GSAP, ni Framer Motion, ni Lenis). Todo es keyframes CSS más un bucle `requestAnimationFrame` propio para el globo |
| Canvas/WebGL | Sí: un único `<canvas>` WebGL para el globo |

Extra interesante: publica un `<link rel="alternate" type="text/markdown">` hacia una versión `index.md` de la página, pensada para LLMs y agentes.

---

## 1. Estructura y jerarquía visual

La home es **una sola pantalla sin scroll**. El contenedor mide `100svh` en mobile y `100vh` en desktop, con `overflow: hidden`. No hay navbar.

```
┌──────────────────────────────────────────────┐
│          logo (wordmark grande)               │  ← header centrado
│          subtítulo en mayúsculas espaciado    │
├───────────────────────┬──────────────────────┤
│                       │  [tarjeta ciudad 1]  │
│     GLOBO 3D          │  [tarjeta ciudad 2]  │  ← grid 2 columnas (md+)
│   (rota solo)         │  [tarjeta ciudad 3]  │
│                       │  [tarjeta ★ pulso ]  │  ← próxima fecha resaltada
│                       │  [tarjeta apagada ]  │  ← deshabilitada
├───────────────────────┴──────────────────────┤
│  ◄ marquee de logos de sponsors ►  [CTA]     │  ← footer: CTA flotando sobre el marquee
└──────────────────────────────────────────────┘
```

Jerarquía, de mayor a menor peso:
1. **Globo**: el elemento más grande y el único en movimiento continuo.
2. **Wordmark**: 72px en desktop y 36px en mobile, en minúsculas con tracking negativo.
3. **Tarjetas de ciudad**: bloques sólidos de alto contraste (negro sobre amarillo). Son la acción principal.
4. **Footer**: logos monocromos y un CTA pequeño centrado.

La relación **lista ↔ globo** es el corazón del diseño: la lista es la navegación y el globo es la visualización. Al hacer hover o focus sobre un ítem, el globo reacciona. No hay tooltips ni popups sobre el globo; toda la información vive en la lista.

---

## 2. Tipografía

Cuatro familias, cada una con un rol claro:

| Rol | Familia | Pesos usados | Tamaño | Tracking | Notas |
|---|---|---|---|---|---|
| Logo / wordmark | **Oxanium** (Google Fonts) | 300 (pedido como `font-light`, pero solo se carga 400/500, así que el navegador lo resuelve con 400) y 500 | 36px mobile / 72px desktop | `-0.05em` (tighter) | Siempre en minúsculas. La parte numérica va en un peso más pesado que el nombre |
| Títulos / labels | **MD Thermochrome** (display de aspecto "pixel/LCD", archivo *Trial*) | 400 | 12px mobile / 20px desktop | `0.05em` en tarjetas y `0.18em` en el subtítulo | Siempre en MAYÚSCULAS, `leading-none` |
| Texto / datos | **Aeonik Mono** | 400, 500 y 700 | 10–12px mobile / 14–16px desktop | normal | Monoespaciada para fechas y países. La fecha va en bold |
| (Otras páginas) | Moderat Mono, Stolzl Display, Geist | — | — | — | Declaradas en el CSS global; no se usan en la home |

Observaciones:
- **Contraste de voces**: una geométrica techno (logo), una display pixelada (labels) y una mono (datos). Las tres comparten un aire "terminal/hardware" sin ser genéricas.
- La escala es muy compacta en mobile: llega a 10px en las fechas. Es legible solo gracias al bold y al contraste.
- La request a Google Fonts pide **12 familias** (Space Grotesk, Sora, Orbitron, JetBrains Mono, etc.), pero la home usa solo Oxanium. Es peso desperdiciado.
- Aeonik y Thermochrome se sirven como **OTF**, no WOFF2: pesan más de lo necesario. Todas las fuentes usan `font-display: swap`.

---

## 3. Paleta de colores

Las variables están definidas en HSL. Equivalentes en hex:

| Token | HSL | Hex | Uso |
|---|---|---|---|
| `--background` (tema claro) | 63 100% 50% | **#F2FF00** | Fondo de toda la página: amarillo ácido |
| `--primary` / `--foreground` | 0 0% 10% | **#1A1A1A** | Texto, tarjetas sólidas, CTA y logos del marquee |
| Acento del globo | — | **#E4FF00** | Hexágonos de los continentes y atmósfera (amarillo un poco más verdoso que el fondo) |
| Cuerpo del globo | — | **#121212** | Esfera con 82% de opacidad, así que se ve como un oliva oscuro sobre el amarillo |
| Marcadores | — | **#FFFFFF** al 90% | Pines finos que salen de cada ciudad, más un halo amarillo con blending aditivo |
| `--secondary` / `--muted` (tema oscuro) | 63 74% 26% | #6E7311 | Oliva para superficies secundarias |
| `--frame-primary` | 118 100% 50% | #09FF00 | Verde neón (otras páginas) |
| `--frame-secondary` | 320 100% 55% | #FF1AB3 | Magenta neón (otras páginas) |

Cómo se usa:
- **Prácticamente dos colores**: amarillo y casi-negro. Todo lo demás son **opacidades del primario**: el estado deshabilitado usa fondo al 15%, borde al 35% y texto al 70%; el separador del footer usa borde al 30%; el texto secundario de las tarjetas, `opacity-80`.
- Las tarjetas **invierten** el esquema: fondo #1A1A1A con texto amarillo. Así el color mismo funciona como affordance de "esto es clickeable".
- Los logos de sponsors se pintan con `mask-image` sobre `bg-primary`. Cualquier logo SVG queda monocromo en el color del tema sin editar los archivos.
- `::selection` también invierte (negro de fondo, amarillo de texto).
- Bordes cuadrados en todo (`rounded-none`): refuerza la estética brutalista.

---

## 4. Animaciones

| Qué | Cuándo | Duración | Easing | Detalle |
|---|---|---|---|---|
| **Entrada escalonada** (`home-reveal`) | Al cargar | 0.7s | `cubic-bezier(.22, 1, .36, 1)`, un ease-out "expo" suave | Opacidad 0→1 y `translateY(10px)`→0. Cada bloque recibe su retraso por una variable CSS: header 80ms, globo 220ms, tarjetas desde 340ms cada 120ms (340, 460, 580, 700, 820), footer 520ms y CTA 640ms. `animation-fill-mode: backwards` evita el parpadeo antes de empezar |
| **Fade del canvas** | Cuando three-globe terminó de cargar | 700ms | ease-out | El contenedor del globo pasa de `opacity-0` a `opacity-100` recién cuando el WebGL está listo. Nunca se ve un canvas vacío ni un "pop" |
| **Rotación del globo** | Siempre (idle) | Continua | Lineal | +0.0018 rad por frame en el eje Y, unos 58s por vuelta a 60fps (depende del frame rate, no del tiempo) |
| **Globo → ciudad** | Hover o focus en una tarjeta | Unos 0.5–1s (exponencial) | `slerp` del cuaternión con factor 0.08 por frame | Calcula la rotación que lleva la ciudad al centro **y la endereza** (el norte queda arriba). Al llegar (ángulo < 0.002) fija la posición. Mientras hay una ciudad activa, **la autorrotación se pausa**; al salir del hover se reanuda desde donde quedó |
| **Pulso de la tarjeta destacada** | Infinito | 2.2s | ease-in-out | `box-shadow` que se expande de 0 a 7px mientras se desvanece (45% → 0%). Es un "ping" de radar que marca la próxima fecha |
| **Marquee de sponsors** | Infinito | ~37s por ciclo (velocidad de 28px/s sobre unos 1047px de recorrido) | Lineal | `translate3d` con la distancia medida por JS. Los bordes se funden con `mask-image: linear-gradient(...)` al 8% de cada lado |
| **Hover en tarjetas y CTA** | Hover | 150ms | `cubic-bezier(.4, 0, .2, 1)` | `scale(1.01)` en tarjetas y `scale(1.02)` en el CTA. Muy sutil |

Nota de implementación: el JS no anima nada del DOM. Solo mide (marquee) y renderiza (globo). Todo lo demás es CSS.

---

## 5. Interacciones y microinteracciones

- **Lista que controla el globo**: `mouseenter`/`focus` fijan la ciudad activa y `mouseleave`/`blur` la limpian. Funciona igual con teclado.
- **Tarjeta deshabilitada**: también reacciona al hover (el globo gira a esa ciudad), pero tiene `cursor: not-allowed`, `aria-disabled` y `tabindex=-1`. Sirve para anticipar el lugar sin que se pueda entrar.
- **CTA sobre el marquee**: el botón queda fijo en el centro mientras los logos pasan por debajo. Un degradado horizontal del color de fondo (transparente → 85% → transparente) "limpia" la zona detrás del botón.
- **Marquee inteligente**: se pausa cuando sale del viewport (IntersectionObserver) y cuando la pestaña está oculta (`visibilitychange`). Esto lo confirmé en vivo. En esta instancia la pausa por hover está desactivada.
- **Cursor**: no hay cursor custom. Usa `pointer` en links, `not-allowed` en la tarjeta deshabilitada y el cursor por defecto en el resto.
- **Navegación**: los links son de Inertia (SPA, sin recarga completa).

---

## 6. Responsive

Breakpoints de Tailwind v4: `sm` 40rem (640px), **`md` 48rem (768px)**, `lg` 64rem, `xl` 80rem y `2xl` 96rem. La home solo usa **`md`**.

| | Mobile (< 768px) | Desktop (≥ 768px) |
|---|---|---|
| Layout | Columna: header → globo (flex-1, toma el espacio sobrante) → tarjetas → footer | Grid de 2 columnas: globo a la izquierda y tarjetas a la derecha, centradas verticalmente |
| Alto | `100svh`, así que la barra de URL de iOS no corta el contenido | `100vh` |
| Padding | 16px laterales | 32px laterales; máximo 1400px de ancho |
| Wordmark | 36px | 72px |
| Tarjetas | Compactas: 52px de alto, padding de 10×4px, textos de 10–12px | Padding de 20×16px, textos de 14–20px |
| Globo (cámara) | FOV 58° y distancia 228 (más cerca, para llenar la pantalla angosta) | FOV 45° y distancia 315 |
| Canvas | Unos 358×427 en 390px | Unos 648×650 en 1440px |

El cambio de cámara lo decide el propio componente leyendo el ancho del contenedor (menos de 768px) con un `ResizeObserver`, no una media query.

**Problema detectado**: como todo está fijado a la altura de la ventana con `overflow: hidden`, en pantallas **bajas** el contenido se recorta. En mi Chrome (viewport de 1536×695) la última tarjeta quedaba 17px por debajo del borde, cortada e inaccesible, y no hay scroll para llegar a ella.

---

## 7. Modo claro / oscuro

- `next-themes` está configurado con **tema oscuro por defecto**: lee `theme` de `localStorage` y agrega `dark` a `<html>` antes de pintar, con un script inline que evita el flash.
- Existen dos temas para esta edición: uno oscuro (amarillo sobre #1A1A1A) y uno claro (el inverso).
- **Pero la home fija el tema claro** en su `<section>`, así que se ve igual en cualquier modo, y no hay toggle visible.
- Efecto colateral: como `<html>` queda con `color-scheme: dark`, **la scrollbar del sistema se pinta oscura sobre una página amarilla** (es la franja gris a la derecha de las capturas de desktop). Es un detalle que se escapó.

---

## 8. Performance y accesibilidad

**Peso** (medido con Playwright; la primera cifra es sin comprimir y la de "transferido" corresponde a la compresión brotli o gzip que sirve Cloudflare):

| Recurso | Sin comprimir | Transferido aprox. |
|---|---|---|
| JS principal (un único bundle para **todo** el sitio) | 7.3 MB | **~2.1 MB** (br) |
| Chunk three-globe (diferido) | 1.0 MB | ~300 KB (gzip) |
| CSS | 217 KB | ~30 KB (br) |
| Fuentes | ~195 KB | — |
| Total desktop | ~9.2 MB en 27 requests | — |
| Total mobile | ~11.4 MB en 44 requests | — |

En mobile hubo más imágenes porque el tap navegó a otra página.

- El bundle principal incluye código de todas las páginas (recharts, i18next, sonner, R3F, términos legales, etc.) y además un **GeoJSON completo de países de Natural Earth embebido** en el JS. No hay code-splitting por ruta, salvo three-globe y el mapa Leaflet.
- Lo que sí está bien: **SSR** (el texto y las tarjetas se ven antes que el JS), el import diferido del 3D, el fade-in del canvas, `setPixelRatio(1)` (barato, aunque en pantallas con DPR 1.25–3 el globo se ve algo blando), y la pausa del marquee fuera de vista o con la pestaña oculta.
- Lo que falta: cancelar el bucle del globo cuando la pestaña está oculta (Chrome lo frena igual, pero no hay lógica explícita) y pausar el globo fuera de viewport.
- FCP en Playwright: ~0.5–0.8s con caché caliente y ~2.1s en frío.

**Movimiento reducido** (`prefers-reduced-motion`):
- ✅ La entrada escalonada solo corre con `no-preference`.
- ✅ El pulso de la tarjeta destacada se desactiva.
- ✅ El fade del canvas tiene `motion-reduce:transition-none`.
- ❌ **El globo sigue rotando** y el giro hacia la ciudad sigue animado: el componente no consulta la preferencia.
- ❌ **El marquee sigue corriendo**: tampoco la consulta.

**Accesibilidad**:
- ❌ `<html>` **sin atributo `lang`**: los lectores de pantalla no saben que el texto está en español.
- ❌ `maximum-scale=1` en el viewport: **bloquea el zoom** con pellizco en mobile.
- ❌ Contraste de la tarjeta deshabilitada: el texto al 70% sobre el fondo al 15% queda bajo para textos de 10–12px.
- ✅ Los logos tienen `role="img"` con `aria-label`, el marquee es una región etiquetada, la tarjeta deshabilitada tiene `aria-disabled`, y la interacción con el globo también funciona con teclado (focus/blur).
- ⚠️ El globo no tiene alternativa textual, pero tampoco hace falta: la lista ya contiene toda la información. Ese patrón es correcto.

---

## 9. Experiencia en vivo

Recorrido en Chrome real (Windows, viewport de 1536×695 con DPR 1.25), complementado con Playwright para mobile y para la línea de tiempo de la entrada.

**Al cargar**
- El amarillo y el texto aparecen casi de inmediato porque el HTML llega con SSR. Después los bloques "suben" 10px mientras aparecen, uno detrás de otro: primero el logo, después el globo, y las tarjetas en cascada de arriba hacia abajo. El footer y el CTA llegan a mitad de la cascada, no al final.
- La sensación es de "carga ordenada", no de espectáculo. Toda la entrada dura alrededor de 1.5s. En la ráfaga de Playwright, a 300ms ya estaban visibles el header y las primeras tarjetas, y a 800ms todo estaba en opacidad 1.
- El globo aparece con un fade propio, separado de la cascada: se nota que llega un instante después que su contenedor, sin un frame en blanco.

**En reposo**
- El globo gira lento hacia la derecha. Los continentes son una trama de puntos/hexágonos amarillos sobre una esfera oscura semitransparente, con un halo amarillo difuso alrededor (la "atmósfera"). Los marcadores son líneas blancas finas que sobresalen como agujas; cuando quedan en el borde de la esfera se leen como "rayos".
- La tarjeta de la próxima fecha (Caracas) late con un anillo que se expande y desaparece cada ~2s. Es lo único "llamativo" fuera del globo y guía la mirada sin gritar.
- Los logos de sponsors se deslizan sin parar; los extremos se desvanecen. El CTA queda quieto encima, con un velo amarillo que lo separa de los logos que pasan por detrás.

**Hover**
- Al pasar el mouse por "Ciudad de México", la autorrotación **se detiene** y el globo gira con desaceleración suave hasta dejar México en el centro, con el norte arriba. El movimiento es rápido al principio y lento al final, sin rebote. Al pasar a otra tarjeta (Caracas), el globo vuelve a moverse desde donde estaba hasta la nueva ciudad, sin volver a cero. Es la microinteracción que más "vende" la página.
- La tarjeta en hover crece apenas (1%); casi no se percibe y no cambia de color. El feedback real es el globo.
- La tarjeta deshabilitada muestra el cursor de prohibido, pero igual mueve el globo hacia Santiago: "todavía no, pero acá va a ser".
- El CTA "sponsor" crece 2% en hover; no tiene cambio de color ni subrayado.
- El cursor es el del sistema: no hay cursor custom ni efectos que sigan al mouse.

**Scroll**
- No hay scroll: la rueda no hace nada. En mi ventana de 695px de alto, la tarjeta de Santiago quedó **cortada** por el borde inferior y no se puede alcanzar.

**Mobile**
- Intenté achicar la ventana de Chrome a 420px de ancho, pero la ventana no cambió de tamaño (probablemente porque está maximizada), así que la prueba mobile la hice con Playwright emulando un iPhone 13 (390×844).
- El globo ocupa casi la mitad superior y se ve más grande gracias a la cámara más cercana. Las cinco tarjetas quedan apiladas y compactas debajo, y el footer con el CTA cierra la pantalla. Todo entra sin scroll en 844px de alto.
- La entrada escalonada es la misma. En pantalla táctil no hay hover, así que **el giro del globo hacia la ciudad no se ve**: el tap navega directo a la página de la ciudad. La interacción estrella de desktop se pierde en mobile.

**Pestaña en segundo plano**
- Con la pestaña oculta, el marquee quedó en `paused` (verificado en vivo).

No grabé GIF: exportarlo implicaba descargar un archivo en tu navegador.

---

## 10. Qué tomar para nuestro proyecto

Contexto: una web de **un solo mapa interactivo con MapLibre**, estética Japón/anime/Pokémon, minimalista, bilingüe EN/ES, modo día/noche, para web y mobile. Estos son principios, no copias.

### Composición
1. **Una pantalla, un protagonista.** El mapa es el globo de Platanus: ocupa la mayor parte y es lo único que se mueve solo. Todo lo demás (título, lista y controles) es chico, plano y quieto.
2. **Lista ↔ mapa como un único sistema.** Un panel con la lista de lugares (regiones, ciudades, gimnasios, etc.) donde hover y focus hacen `flyTo`/`easeTo` en MapLibre, y el marcador del mapa resalta el ítem de la lista. La lista es además la **alternativa accesible** del mapa, así que no hace falta describir el canvas.
3. **En mobile, no depender del hover.** Platanus pierde su mejor interacción en táctil. Para nosotros: un primer tap selecciona (vuela el mapa y muestra una ficha), y un segundo tap o un botón explícito abre el detalle. En mobile, lista en **bottom sheet**; en desktop, panel lateral. Breakpoint único en 768px, como ellos: es suficiente.
4. **Que el layout de una pantalla no recorte.** Usar `100dvh`/`100svh` para el contenedor del mapa, pero dejar que el **panel** tenga su propio scroll interno. Nunca `overflow: hidden` sobre contenido navegable.

### Color
5. **Dos tintas más opacidades.** Elegir un par fuerte (por ejemplo, papel washi y sumi para el día, índigo y una luz cálida para la noche) y derivar todos los estados (deshabilitado, borde, secundario) con transparencias del color principal. Definir los tokens como variables CSS y conmutar día/noche cambiando solo las variables, como hacen ellos con sus dos temas.
6. **El estilo del mapa sigue al tema.** Con MapLibre, tener dos style JSON (o cambiar `paint` properties en caliente) que usen **los mismos tokens** que la UI, para que el mapa no parezca un componente ajeno. Un mapa casi monocromo con un único color de acento para los puntos de interés reproduce el efecto "hexágonos amarillos sobre esfera oscura".
7. **Un único acento con función.** Su amarillo es la marca y la llamada a la acción. Para nosotros, un rojo (hinomaru/Pokébola) o similar reservado **solo** para lo interactivo o seleccionado.
8. **Íconos monocromos vía `mask-image`.** Pintar íconos SVG (tipos de Pokémon, categorías) con el color del tema sin duplicar archivos por modo.
9. **Sincronizar `color-scheme`** con el tema realmente visible (para no repetir su scrollbar oscura sobre fondo claro).

### Tipografía
10. **Tres voces con roles fijos:** una display con personalidad para el título (algo con aire de cartel o videojuego), una para labels en MAYÚSCULAS con tracking amplio, y una mono o sans muy legible para los datos. Para japonés, hace falta una familia con kana/kanji (por ejemplo, Noto Sans JP o M PLUS) como **fallback del stack**, no como fuente principal.
11. **Cargar solo las fuentes y pesos que se usan**, en WOFF2 y con subsetting (en japonés, **dividir por unicode-range** o cargar solo los glifos usados). Ellos piden 12 familias y usan una.

### Movimiento
12. **Entrada escalonada solo con CSS**: opacidad más `translateY` de unos 10px, ~0.7s, con un ease-out tipo `cubic-bezier(.22,1,.36,1)` y retrasos por variable CSS (~120ms entre ítems). Sin librería.
13. **No mostrar el mapa hasta que esté listo**: contenedor en `opacity: 0` y fade al recibir el evento `load` o `idle` de MapLibre.
14. **Un solo "pulso" de atención**: un anillo que late en el marcador o ítem más relevante (por ejemplo, "evento actual" o "tu ubicación"). Uno solo, nunca varios.
15. **Movimiento idle muy lento.** Si el mapa gira o tiene un paneo ambiental (por ejemplo, un `bearing` lento o el ciclo del cielo en modo noche), que se **detenga en cuanto el usuario interactúa** y no vuelva de golpe.
16. **Respetar `prefers-reduced-motion` en todo, incluido el canvas**: ellos lo respetan en CSS pero no en el globo ni en el marquee. En MapLibre, `flyTo` → `jumpTo` (o `duration: 0`), sin rotación idle y sin pulso.
17. **Pausar lo que no se ve**: frenar animaciones propias con `visibilitychange` e `IntersectionObserver`, como hacen con el marquee.

### Performance
18. **Code-splitting real**: MapLibre (~800 KB) en import diferido, mostrando primero el shell SSR o estático. Datos geográficos en archivos aparte (vector tiles o PMTiles), **nunca embebidos en el JS**.
19. **Pixel ratio con criterio**: MapLibre ya maneja el DPR, pero conviene limitarlo con `pixelRatio: Math.min(devicePixelRatio, 2)` en mobile para no quemar batería.
20. **Presupuesto**: apuntar a menos de 300 KB de JS inicial (comprimido), frente a sus ~2.1 MB.

### Bilingüe EN/ES
21. **`<html lang>` correcto y dinámico** (ellos no lo tienen). Cambiar `lang` al cambiar de idioma; los nombres japoneses dentro del texto pueden ir con `lang="ja"` para que la fuente y la pronunciación sean correctas.
22. **Etiquetas del mapa en el idioma activo**: MapLibre permite expresiones como `["coalesce", ["get", "name:es"], ["get", "name"]]`. Mostrar el nombre local en japonés como dato secundario es un buen guiño estético.
23. **Selector de idioma y de día/noche como dos controles mínimos** en una esquina, persistidos en `localStorage`. El modo inicial debe salir de `prefers-color-scheme` y aplicarse con un script inline antes de pintar (su patrón anti-flash está bien resuelto).

### Accesibilidad
24. **No bloquear el zoom** (sin `maximum-scale=1`). En un mapa, el gesto de pellizco lo maneja MapLibre dentro del canvas; la UI tiene que poder ampliarse igual.
25. **Teclado**: que los ítems de la lista sean enfocables y que focus dispare la misma acción que hover (ellos lo hacen bien), además de controles de zoom accesibles.
26. **Estados deshabilitados legibles**: atenuar menos que ellos para mantener un contraste de al menos 4.5:1 en textos chicos.

### Extra
27. **Una versión en texto de la página** (`/index.md` o `llms.txt`) con la lista de lugares: es barato y hace el contenido indexable por agentes.
