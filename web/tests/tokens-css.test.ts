// El CSS generado está al día con tokens.ts y apunta a fuentes que existen.
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { buildTokensCss } from "../tokens/css.ts";

const generated = readFileSync(fileURLToPath(new URL("../app/tokens.css", import.meta.url)), "utf8");
const publicDir = fileURLToPath(new URL("../public", import.meta.url));

describe("app/tokens.css", () => {
  it("está sincronizado con tokens/tokens.ts (correr `npm run tokens`)", () => {
    expect(generated).toBe(buildTokensCss());
  });

  it("cada @font-face apunta a un WOFF2 existente en public/fonts (correr `npm run fonts`)", () => {
    const urls = [...generated.matchAll(/url\("([^"]+)"\)/g)].map((m) => m[1]);
    expect(urls.length).toBeGreaterThan(0);
    for (const url of urls) {
      expect(url).toMatch(/^\/fonts\/.+\.woff2$/);
      expect(existsSync(publicDir + url), url).toBe(true);
    }
  });

  it("desactiva la paleta, fuentes y radios por defecto de Tailwind", () => {
    for (const reset of ["--color-*: initial;", "--font-*: initial;", "--radius-*: initial;", "--spacing: initial;"]) {
      expect(generated).toContain(reset);
    }
  });

  it("con reduced-motion todo dura 0 ms salvo los fades", () => {
    const reduced = generated.split("@media (prefers-reduced-motion: reduce)")[1].split("}")[0];
    expect(reduced).toMatch(/--dur-fly: 0ms;/);
    expect(reduced).toMatch(/--dur-pulse: 0ms;/);
    expect(reduced).toMatch(/--dur-fade: 150ms;/);
  });
});
