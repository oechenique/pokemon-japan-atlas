// Fase 0: página mínima para comprobar tokens y fuentes. El shell real llega en la Fase 4.
export default function Home() {
  return (
    <main className="mx-auto flex min-h-dvh max-w-page flex-col justify-center gap-4 px-(--gutter)">
      <h1 className="font-wordmark text-wordmark">
        pokemon japan atlas <span className="text-accent">[30]</span>
      </h1>
      <p className="font-label text-subtitle uppercase">30 años · 30 días · 1 pipeline</p>
      <p className="text-data-sm text-ink-80">Fase 0 · esqueleto</p>
    </main>
  );
}
