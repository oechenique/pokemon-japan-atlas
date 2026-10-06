// Fuente única de los design tokens (reglas/01-design-tokens.md).
// De acá se generan las variables CSS y el tema de Tailwind (`npm run tokens`)
// y, desde la Fase 4, los estilos del mapa. Ningún componente escribe colores,
// fuentes ni duraciones a mano.

export type Theme = "day" | "night" | "gameboy";

export interface Palette {
  bg: string;
  ink: string;
  inkInverse: string;
  accent: string;
}

// Dos tintas por modo + un único acento.
export const palettes: Record<Theme, Palette & { fill?: string }> = {
  day: { bg: "#F4EFE6", ink: "#1A1A1A", inkInverse: "#F4EFE6", accent: "#E3350D" },
  night: { bg: "#0F1A2E", ink: "#FFD27A", inkInverse: "#0F1A2E", accent: "#E3350D" },
  // Easter egg (código Konami). Fuera del test de contraste por excepción documentada.
  gameboy: { bg: "#9BBC0F", ink: "#0F380F", inkInverse: "#9BBC0F", accent: "#306230", fill: "#8BAC0F" },
};

// Estados derivados: opacidad de --ink, nunca colores nuevos.
export const inkAlpha = { "ink-80": 0.8, "ink-35": 0.35, "ink-15": 0.15 } as const;

export const fallbackStack = `system-ui, "Hiragino Sans", "Yu Gothic", sans-serif`;

export const fonts = {
  wordmark: { family: "Dela Gothic One", file: "dela-gothic-one", weights: [400] },
  label: { family: "DotGothic16", file: "dotgothic16", weights: [400] },
  data: { family: "M PLUS 1 Code", file: "m-plus-1-code", weights: [400, 700] },
} as const;

// Hasta la Fase 4 solo se carga latín (incluye latin-ext por las macrones: Kantō, Kyūshū).
export const fontSubsets = {
  latin:
    "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD",
  "latin-ext":
    "U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+0304, U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, U+20AD-20C0, U+2113, U+2C60-2C7F, U+A720-A7FF",
} as const;

// Tamaños tipográficos [mobile, desktop] en px.
export const typeScale = {
  wordmark: { mobile: 32, desktop: 64, tracking: "-0.03em" },
  label: { mobile: 12, desktop: 18, tracking: "0.08em" },
  subtitle: { mobile: 12, desktop: 18, tracking: "0.18em" },
  data: { mobile: 13, desktop: 16, tracking: "normal" },
  "data-sm": { mobile: 12, desktop: 14, tracking: "normal" },
} as const;

export const spacing = [4, 8, 12, 16, 24, 32, 48, 64] as const;

export const layout = { gutterMobile: 16, gutterDesktop: 32, maxWidth: 1400, breakpoint: 768 } as const;

export const motion = {
  ease: { out: "cubic-bezier(.22, 1, .36, 1)", standard: "cubic-bezier(.4, 0, .2, 1)" },
  duration: { fast: 150, base: 400, reveal: 700, stagger: 120, fly: 1600, pulse: 2200 },
  // Con prefers-reduced-motion todo pasa a 0 ms salvo los fades de opacidad.
  reducedFade: 150,
} as const;

// Pares que vigila el test de contraste. "over" es el fondo sobre el que se
// compone el color cuando tiene opacidad (p. ej. --ink-80 sobre la tarjeta apagada).
export type ContrastKind = "text" | "component";
export interface ContrastPair {
  name: string;
  kind: ContrastKind;
  fg: keyof Palette | keyof typeof inkAlpha;
  bg: keyof Palette | keyof typeof inkAlpha;
}

export const contrastPairs: ContrastPair[] = [
  { name: "texto sobre la página", kind: "text", fg: "ink", bg: "bg" },
  { name: "texto de tarjeta sólida", kind: "text", fg: "inkInverse", bg: "ink" },
  { name: "texto secundario", kind: "text", fg: "ink-80", bg: "bg" },
  { name: "texto deshabilitado sobre tarjeta apagada", kind: "text", fg: "ink-80", bg: "ink-15" },
  { name: "acento (UI, texto grande, foco) sobre la página", kind: "component", fg: "accent", bg: "bg" },
  { name: "tarjeta sólida contra la página", kind: "component", fg: "ink", bg: "bg" },
];

export const contrastThreshold: Record<ContrastKind, number> = { text: 4.5, component: 3 };
