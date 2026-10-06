// Genera app/tokens.css (variables CSS + @font-face + tema de Tailwind) a partir de tokens.ts.
import {
  fallbackStack,
  fontSubsets,
  fonts,
  inkAlpha,
  layout,
  motion,
  palettes,
  spacing,
  typeScale,
  type Theme,
} from "./tokens.ts";

const px = (n: number) => `${n}px`;
const ms = (n: number) => `${n}ms`;

export const fontFile = (file: string, subset: string, weight: number) =>
  `/fonts/${file}-${subset}-${weight}-normal.woff2`;

// Archivos que el layout precarga: subset latino básico, peso 400 (el 700 solo aparece en fechas).
export const preloadFonts = Object.values(fonts).map((f) => fontFile(f.file, "latin", 400));

function fontFaces(): string {
  return Object.values(fonts)
    .flatMap((f) =>
      f.weights.flatMap((w) =>
        Object.entries(fontSubsets).map(
          ([subset, range]) => `@font-face {
  font-family: "${f.family}";
  font-style: normal;
  font-weight: ${w};
  font-display: swap;
  src: url("${fontFile(f.file, subset, w)}") format("woff2");
  unicode-range: ${range};
}`,
        ),
      ),
    )
    .join("\n");
}

function themeVars(theme: Theme): string {
  const p = palettes[theme];
  const lines = [
    `--bg: ${p.bg};`,
    `--ink: ${p.ink};`,
    `--ink-inverse: ${p.inkInverse};`,
    `--accent: ${p.accent};`,
    `color-scheme: ${theme === "night" ? "dark" : "light"};`,
  ];
  if (p.fill) lines.push(`--fill: ${p.fill};`);
  // Game Boy: el texto va siempre en --ink, sin opacidades.
  if (theme === "gameboy") lines.push(`--ink-80: var(--ink);`);
  return lines.map((l) => `  ${l}`).join("\n");
}

function typeVars(size: "mobile" | "desktop"): string {
  return Object.entries(typeScale)
    .map(([name, t]) => `  --fs-${name}: ${px(t[size])};`)
    .join("\n");
}

function durationVars(reduced: boolean): string {
  const d = motion.duration;
  const v = (n: number) => ms(reduced ? 0 : n);
  return [
    `--dur-fast: ${v(d.fast)};`,
    `--dur-base: ${v(d.base)};`,
    `--dur-reveal: ${v(d.reveal)};`,
    `--stagger: ${v(d.stagger)};`,
    `--dur-fly: ${v(d.fly)};`,
    `--dur-pulse: ${v(d.pulse)};`,
    `--dur-fade: ${ms(reduced ? motion.reducedFade : d.base)};`,
  ]
    .map((l) => `  ${l}`)
    .join("\n");
}

function tailwindTheme(): string {
  const colors = ["bg", "ink", "ink-inverse", "accent", ...Object.keys(inkAlpha)]
    .map((c) => `  --color-${c}: var(--${c});`)
    .join("\n");
  const families = Object.entries(fonts)
    .map(([role, f]) => `  --font-${role}: "${f.family}", ${fallbackStack};`)
    .join("\n");
  const text = Object.entries(typeScale)
    .map(
      ([name, t]) =>
        `  --text-${name}: var(--fs-${name});\n  --text-${name}--letter-spacing: ${t.tracking};`,
    )
    .join("\n");
  const space = spacing.map((n) => `  --spacing-${n / 4}: ${px(n)};`).join("\n");
  return `@theme inline {
  /* Sin paleta, fuentes, tamaños ni radios por defecto de Tailwind: solo tokens. */
  --color-*: initial;
${colors}
  --font-*: initial;
${families}
  --text-*: initial;
${text}
  --spacing: initial;
  --spacing-*: initial;
  --spacing-px: 1px;
${space}
  --radius-*: initial;
  --breakpoint-*: initial;
  --breakpoint-md: ${layout.breakpoint / 16}rem;
  --container-*: initial;
  --container-page: ${px(layout.maxWidth)};
  --ease-*: initial;
  --ease-out: ${motion.ease.out};
  --ease-standard: ${motion.ease.standard};
  --animate-*: initial;
}`;
}

export function buildTokensCss(): string {
  const alpha = Object.entries(inkAlpha)
    .map(([name, a]) => `  --${name}: color-mix(in srgb, var(--ink) ${a * 100}%, transparent);`)
    .join("\n");
  return `/* GENERADO por \`npm run tokens\` a partir de tokens/tokens.ts. No editar a mano. */

${fontFaces()}

/* Día por defecto; noche si el sistema la prefiere y no hay tema elegido. */
:root,
[data-theme="day"] {
${themeVars("day")}
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme]) {
${themeVars("night")}
  }
}

[data-theme="night"] {
${themeVars("night")}
}

:root {
${alpha}
  --gutter: ${px(layout.gutterMobile)};
${typeVars("mobile")}
  --ease-out: ${motion.ease.out};
  --ease-standard: ${motion.ease.standard};
${durationVars(false)}
}

[data-theme="gameboy"] {
${themeVars("gameboy")}
}

@media (min-width: ${px(layout.breakpoint)}) {
  :root {
    --gutter: ${px(layout.gutterDesktop)};
${typeVars("desktop").replace(/^/gm, "  ")}
  }
}

@media (prefers-reduced-motion: reduce) {
  :root {
${durationVars(true).replace(/^/gm, "  ")}
  }
}

${tailwindTheme()}
`;
}
