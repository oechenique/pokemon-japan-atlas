import type { Metadata } from "next";
import { preloadFonts } from "@/tokens/css.ts";
import "./globals.css";

export const metadata: Metadata = {
  title: "pokemon japan atlas [30]",
  description: "30 años, 30 días, 1 pipeline. El Japón detrás de 30 años de Pokémon.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // El idioma y el tema dinámicos llegan en la Fase 5; sin data-theme manda prefers-color-scheme.
    <html lang="es">
      <head>
        {preloadFonts.map((href) => (
          <link key={href} rel="preload" href={href} as="font" type="font/woff2" crossOrigin="" />
        ))}
      </head>
      <body className="min-h-dvh">{children}</body>
    </html>
  );
}
