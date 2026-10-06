// Copia a public/fonts/ los WOFF2 que pide tokens.ts (subsets latin y latin-ext)
// desde los paquetes @fontsource (OFL-1.1), junto con sus licencias.
// Los archivos quedan versionados: el build no depende de la red.
// Uso: `npm run fonts` (solo al cambiar fuentes, pesos o subsets).
import { copyFileSync, mkdirSync, readdirSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { fontSubsets, fonts } from "../tokens/tokens.ts";

const require = createRequire(import.meta.url);
const outDir = fileURLToPath(new URL("../public/fonts/", import.meta.url));

rmSync(outDir, { recursive: true, force: true });
mkdirSync(outDir, { recursive: true });

for (const font of Object.values(fonts)) {
  const pkg = dirname(require.resolve(`@fontsource/${font.file}/package.json`));
  for (const weight of font.weights) {
    for (const subset of Object.keys(fontSubsets)) {
      const name = `${font.file}-${subset}-${weight}-normal.woff2`;
      copyFileSync(join(pkg, "files", name), join(outDir, name));
    }
  }
  copyFileSync(join(pkg, "LICENSE"), join(outDir, `${font.file}.OFL.txt`));
}

console.log(readdirSync(outDir).join("\n"));
