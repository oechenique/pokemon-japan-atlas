Analizá a fondo el sitio https://hack.platan.us/ como referencia de diseño
para un proyecto propio. Solo analizar: no copies código, assets ni textos
del sitio a nuestro repo; queremos entender qué lo hace funcionar, no clonarlo.

1. Bajá el HTML, el CSS y los bundles JS. Identificá framework, librerías
   de animación (GSAP, Framer Motion, Lenis, Three.js, etc.) y si usa
   canvas/WebGL.
2. Si podés instalar Playwright, sacá capturas en desktop (1440px) y mobile
   (390px), al cargar y después de scrollear/interactuar. Guardalas en
   referencias/platanus/capturas/.
3. Escribí referencias/platanus/ANALISIS.md con:
   - Estructura de la página y jerarquía visual
   - Tipografías (familias, pesos, tamaños, tracking)
   - Paleta de colores (hex) y cómo se usan
   - Animaciones: qué se anima, cuándo (carga, hover, scroll), duraciones
     y easings
   - Interacciones y microinteracciones
   - Responsive: breakpoints y qué cambia en mobile
   - Modo claro/oscuro, si existe
   - Performance y accesibilidad (peso de la página, prefers-reduced-motion)
   - Sección final: "Qué tomar para nuestro proyecto": principios concretos
     y aplicables (no copias) para una web de un solo mapa interactivo
     con MapLibre, estética Japón/anime/Pokémon, minimalista, bilingüe
     EN/ES, modo día/noche, web y mobile.