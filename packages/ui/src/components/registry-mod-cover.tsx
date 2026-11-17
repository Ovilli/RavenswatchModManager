/** Deterministic cover art shared by registry cards and detail pages. */
const GROUNDS = [
  ['hsl(357 57% 20%)', 'hsl(0 49% 6%)'],
  ['hsl(350 45% 17%)', 'hsl(10 40% 5%)'],
  ['hsl(8 50% 18%)', 'hsl(0 49% 5%)'],
  ['hsl(340 35% 16%)', 'hsl(355 45% 6%)'],
] as const;

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function initial(name: string): string {
  const letter = name.match(/\p{L}|\p{N}/u)?.[0];
  return letter ? letter.toUpperCase() : '?';
}

export function RegistryModCover({
  seed,
  name,
  className = '',
  size = 'md',
}: {
  seed: string;
  name: string;
  className?: string;
  size?: 'sm' | 'md' | 'lg';
}) {
  const h = hash(seed || name);
  const [from, to] = GROUNDS[h % GROUNDS.length] ?? GROUNDS[0];
  const angle = 115 + (h % 50);
  const x = 30 + ((h >> 8) % 40);
  const letterSize = size === 'sm' ? 'text-2xl' : size === 'lg' ? 'text-8xl' : 'text-6xl';

  return (
    <div
      aria-hidden="true"
      className={`relative flex items-center justify-center overflow-hidden ${className}`}
      style={{
        backgroundColor: to,
        backgroundImage: `repeating-linear-gradient(${angle}deg, hsl(41 60% 60% / 0.05) 0 1px, transparent 1px 11px), radial-gradient(ellipse at ${x}% 20%, ${from}, ${to} 75%)`,
      }}
    >
      {size !== 'sm' ? <span className="pointer-events-none absolute inset-3 border border-gilt/15" /> : null}
      <span className={`font-display ${letterSize} leading-none text-gilt/80 drop-shadow-[0_2px_8px_rgb(0_0_0/0.6)]`}>
        {initial(name)}
      </span>
    </div>
  );
}
