// Escribe app/tokens.css a partir de tokens/tokens.ts. Uso: `npm run tokens`.
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { buildTokensCss } from "../tokens/css.ts";

const out = fileURLToPath(new URL("../app/tokens.css", import.meta.url));
writeFileSync(out, buildTokensCss());
console.log(`tokens → ${out}`);
