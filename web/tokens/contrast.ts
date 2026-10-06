// Contraste WCAG 2.x a partir de los tokens. Lo usa el test de contraste.
import { inkAlpha, type ContrastPair, type Palette } from "./tokens.ts";

type RGB = [number, number, number];

export function hexToRgb(hex: string): RGB {
  const m = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!m) throw new Error(`Color inválido: ${hex}`);
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

// Composición alfa de fg sobre bg (lo que hace el navegador con color-mix(... transparent)).
export function blend(fg: RGB, bg: RGB, alpha: number): RGB {
  return fg.map((c, i) => c * alpha + bg[i] * (1 - alpha)) as RGB;
}

function luminance([r, g, b]: RGB): number {
  const lin = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

export function contrastRatio(a: RGB, b: RGB): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

// Resuelve un token de color (sólido o derivado con opacidad) a RGB compuesto sobre `under`.
export function resolveToken(palette: Palette, token: ContrastPair["fg"], under: RGB): RGB {
  if (token in inkAlpha) {
    return blend(hexToRgb(palette.ink), under, inkAlpha[token as keyof typeof inkAlpha]);
  }
  return hexToRgb(palette[token as keyof Palette]);
}

// El fondo se compone sobre la página y el texto, sobre ese fondo.
export function pairRatio(palette: Palette, pair: ContrastPair): number {
  const surface = resolveToken(palette, pair.bg, hexToRgb(palette.bg));
  return contrastRatio(resolveToken(palette, pair.fg, surface), surface);
}
