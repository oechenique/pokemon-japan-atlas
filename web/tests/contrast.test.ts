// Vigila los contrastes de reglas/01-design-tokens.md en día y noche.
import { describe, expect, it } from "vitest";
import { blend, contrastRatio, hexToRgb, pairRatio } from "../tokens/contrast.ts";
import { contrastPairs, contrastThreshold, palettes } from "../tokens/tokens.ts";

describe.each(["day", "night"] as const)("contraste en modo %s", (theme) => {
  it.each(contrastPairs)("$name ($kind)", (pair) => {
    const ratio = pairRatio(palettes[theme], pair);
    expect(ratio, `${pair.fg} sobre ${pair.bg} = ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(
      contrastThreshold[pair.kind],
    );
  });
});

describe("Game Boy (excepción documentada)", () => {
  it("el texto, siempre --ink sobre --bg, sigue siendo legible", () => {
    const { ink, bg } = palettes.gameboy;
    expect(contrastRatio(hexToRgb(ink), hexToRgb(bg))).toBeGreaterThanOrEqual(contrastThreshold.text);
  });
});

describe("cálculo de contraste", () => {
  it("coincide con los valores de referencia de WCAG", () => {
    expect(contrastRatio(hexToRgb("#000000"), hexToRgb("#FFFFFF"))).toBeCloseTo(21, 5);
    expect(contrastRatio(hexToRgb("#777777"), hexToRgb("#FFFFFF"))).toBeCloseTo(4.48, 2);
  });

  it("al 60% el texto deshabilitado no alcanzaría (motivo de usar --ink-80)", () => {
    const ink = hexToRgb(palettes.day.ink);
    const disabledCard = blend(ink, hexToRgb(palettes.day.bg), 0.15);
    const ratio = contrastRatio(blend(ink, disabledCard, 0.6), disabledCard);
    expect(ratio).toBeLessThan(contrastThreshold.text);
  });
});
