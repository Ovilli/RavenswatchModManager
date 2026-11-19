import { type CSSProperties, type ReactNode, useEffect, useId, useRef } from 'react';
import hero1 from '../assets/library-heroes/hero-1.png';
import hero2 from '../assets/library-heroes/hero-2.png';
import hero3 from '../assets/library-heroes/hero-3.png';
import hero4 from '../assets/library-heroes/hero-4.png';
import hero5 from '../assets/library-heroes/hero-5.png';
import hero6 from '../assets/library-heroes/hero-6.png';
import { LibrarySpellbook } from './library-spellbook';
import './library-empty-state.css';

// User-supplied hero portraits, bundled locally for the Library illustration.
const HERO_PORTRAITS = [
  {
    src: hero1,
    x: '13%',
    y: '51%',
    tilt: '-16deg',
    ink: '356 65% 66%',
    motion: { pace: 0.94, phase: 0.77, turn: 1.08, zoom: 0.97, depth: 1.06, reach: 0.97 },
  },
  {
    src: hero2,
    x: '29%',
    y: '19%',
    tilt: '12deg',
    ink: '30 74% 66%',
    motion: { pace: 1.08, phase: 0.335, turn: 0.93, zoom: 1.04, depth: 0.96, reach: 1 },
  },
  {
    src: hero3,
    x: '53%',
    y: '11%',
    tilt: '-8deg',
    ink: '205 37% 71%',
    motion: { pace: 0.98, phase: 0.742, turn: 1.04, zoom: 0.94, depth: 1.09, reach: 0.94 },
  },
  {
    src: hero4,
    x: '78%',
    y: '27%',
    tilt: '17deg',
    ink: '101 27% 63%',
    motion: { pace: 1.04, phase: 0.092, turn: 0.96, zoom: 1.07, depth: 0.92, reach: 0.99 },
  },
  {
    src: hero5,
    x: '87%',
    y: '63%',
    tilt: '-13deg',
    ink: '187 38% 66%',
    motion: { pace: 0.91, phase: 0.817, turn: 1.1, zoom: 1.02, depth: 1.03, reach: 0.96 },
  },
  {
    src: hero6,
    x: '30%',
    y: '79%',
    tilt: '19deg',
    ink: '41 60% 67%',
    motion: { pace: 1.01, phase: 0.53, turn: 0.91, zoom: 0.99, depth: 0.98, reach: 0.95 },
  },
] as const;

// Keep each card's small variations stable across renders. Independent periods
// drift past one another; grouped starting phases allow simultaneous returns.
const FLIGHT_SECONDS = 10.8;

export function LibraryEmptyState({
  title,
  body,
  action,
}: {
  title: ReactNode;
  body?: string;
  action?: ReactNode;
}) {
  const titleId = useId();
  const artRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const art = artRef.current;
    if (!art) return;
    let visible = false;
    const syncPlayback = () => {
      art.dataset.motionPaused = String(!visible || document.hidden);
    };
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry) return;
      visible = entry.isIntersecting;
      syncPlayback();
    });
    observer.observe(art);
    document.addEventListener('visibilitychange', syncPlayback);
    return () => {
      observer.disconnect();
      document.removeEventListener('visibilitychange', syncPlayback);
    };
  }, []);

  return (
    <section className="empty-grimoire" aria-labelledby={titleId}>
      <div className="empty-grimoire-scene">
        <div
          ref={artRef}
          className="empty-grimoire-art"
          data-motion-paused="true"
          aria-hidden="true"
        >
          <div className="empty-grimoire-aura" />
          <LibrarySpellbook />
          <div className="empty-grimoire-flights">
            {HERO_PORTRAITS.map((portrait, index) => (
              <div
                key={portrait.src}
                className="empty-grimoire-flight-track"
                style={
                  {
                    '--flight-x': `calc(${portrait.x} - 50%)`,
                    '--flight-y': `calc(${portrait.y} - 78%)`,
                    '--portrait-tilt': portrait.tilt,
                    '--portrait-ink': portrait.ink,
                    '--flight-duration': `${FLIGHT_SECONDS * portrait.motion.pace}s`,
                    '--flight-delay': `${-FLIGHT_SECONDS * portrait.motion.pace * portrait.motion.phase}s`,
                    '--flight-reach': portrait.motion.reach,
                    '--flight-depth': `${-160 * portrait.motion.depth}px`,
                    '--flight-zoom': 1.05 * portrait.motion.zoom,
                    '--turn-variance': portrait.motion.turn,
                    '--spin': index % 2 === 0 ? 1 : -1,
                  } as CSSProperties
                }
              >
                <div className="empty-grimoire-portrait">
                  <div className="empty-grimoire-card">
                    <div className="empty-grimoire-portrait-face">
                      <img src={portrait.src} alt="" width={256} height={256} draggable={false} />
                    </div>
                    <div className="empty-grimoire-portrait-back">
                      <svg viewBox="0 0 40 40" fill="none" aria-hidden="true">
                        <path d="m20 5 4 11 11 4-11 4-4 11-4-11L5 20l11-4Z" />
                        <circle cx="20" cy="20" r="15" />
                      </svg>
                    </div>
                  </div>
                </div>
                <span className="empty-grimoire-summon-dust" />
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="empty-grimoire-copy">
        <h3 id={titleId} className="font-fraktur">
          {title}
        </h3>
        {body ? <p>{body}</p> : null}
        {action ? <div className="empty-grimoire-action">{action}</div> : null}
      </div>
    </section>
  );
}
