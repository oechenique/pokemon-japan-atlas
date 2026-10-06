// Ningún color, fuente, radio ni duración se escribe a mano fuera de los tokens (reglas/01).
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const root = fileURLToPath(new URL("..", import.meta.url));
const scanned = ["app", "components", "lib"];
// Únicos archivos que pueden contener valores crudos: los tokens y su CSS generado.
const allowed = new Set(["app/tokens.css"]);

function walk(dir: string): string[] {
  let entries: string[];
  try {
    entries = readdirSync(dir);
  } catch {
    return [];
  }
  return entries.flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return walk(path);
    return /\.(tsx?|css)$/.test(name) ? [path] : [];
  });
}

const files = scanned
  .flatMap((d) => walk(join(root, d)))
  .map((p) => relative(root, p).replaceAll("\\", "/"))
  .filter((p) => !allowed.has(p));

const forbidden: [string, RegExp][] = [
  ["color hex", /#[0-9a-f]{3,8}\b/i],
  ["función de color", /\b(rgba?|hsla?|oklch|oklab|lab|lch|hwb)\(/i],
  ["valor arbitrario de Tailwind con color", /-\[(#|rgb|hsl|oklch|color-mix|var\(--(?!bg|ink|accent))/i],
  ["radio distinto de cero", /\brounded-(?!none\b)[\w-]+/],
  ["duración o retardo a mano", /\b(duration|delay)-\d+|\b\d+m?s\b(?![\w-])/],
  ["familia tipográfica a mano", /font-family:(?!\s*var\()|fontFamily:\s*["'`]|\bfont-\[/],
  ["Google Fonts en runtime", /fonts\.(googleapis|gstatic)\.com/],
  ["zoom bloqueado", /maximum-scale|user-scalable/],
];

describe("guardia de estilo", () => {
  it("encuentra los archivos de la app", () => {
    expect(files).toContain("app/page.tsx");
  });

  it.each(files)("%s solo usa tokens", (file) => {
    const source = readFileSync(join(root, file), "utf8");
    const hits = forbidden
      .filter(([, re]) => re.test(source))
      .map(([what, re]) => `${what}: ${source.match(re)?.[0]}`);
    expect(hits).toEqual([]);
  });
});
