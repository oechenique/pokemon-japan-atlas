import type { NextConfig } from "next";

// Export estático (reglas/00): la web es un snapshot sin servidor.
// Por eso no se activa cacheComponents, que requiere un runtime de Node.
const nextConfig: NextConfig = {
  output: "export",
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
