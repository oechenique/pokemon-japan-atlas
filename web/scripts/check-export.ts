// Verifica el export estático (out/) contra reglas/02: correr después de `npm run build`.
import { existsSync, readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { fileURLToPath } from "node:url";
import { preloadFonts } from "../tokens/css.ts";

const out = fileURLToPath(new URL("../out", import.meta.url));
const JS_BUDGET_GZIP = 300 * 1024;

const failures: string[] = [];
const check = (ok: boolean, message: string) => {
  console.log(`${ok ? "✓" : "✗"} ${message}`);
  if (!ok) failures.push(message);
};

const indexPath = `${out}/index.html`;
if (!existsSync(indexPath)) {
  console.error("✗ falta out/index.html: corré `npm run build` primero");
  process.exit(1);
}
const html = readFileSync(indexPath, "utf8");

check(/<html[^>]*\slang="(es|en)"/.test(html), "<html> declara lang");
check(!/maximum-scale|user-scalable/.test(html), "el viewport no bloquea el zoom");

const external = [...html.matchAll(/(?:src|href)="(https?:\/\/[^"]+)"/g)].map((m) => m[1]);
check(external.length === 0, `sin recursos externos en runtime${external.length ? `: ${external.join(", ")}` : ""}`);

for (const font of preloadFonts) {
  check(html.includes(font) && existsSync(out + font), `fuente precargada y exportada: ${font}`);
}

const scripts = [...new Set([...html.matchAll(/<script[^>]+src="([^"]+\.js)"/g)].map((m) => m[1]))];
const gzipped = scripts.reduce((sum, src) => sum + gzipSync(readFileSync(out + src)).length, 0);
check(
  gzipped < JS_BUDGET_GZIP,
  `JS inicial ${(gzipped / 1024).toFixed(1)} KB gzip (presupuesto ${JS_BUDGET_GZIP / 1024} KB, ${scripts.length} archivos)`,
);

if (failures.length) {
  console.error(`\n${failures.length} chequeo(s) fallaron`);
  process.exit(1);
}
