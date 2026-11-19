import { type CSSProperties, type ReactNode, useId } from 'react';
import hero1 from '../assets/library-heroes/hero-1.png';
import hero2 from '../assets/library-heroes/hero-2.png';
import hero3 from '../assets/library-heroes/hero-3.png';
import hero4 from '../assets/library-heroes/hero-4.png';
import hero5 from '../assets/library-heroes/hero-5.png';
import hero6 from '../assets/library-heroes/hero-6.png';
import './library-empty-state.css';

// User-supplied hero portraits, bundled locally for the Library illustration.
const HERO_PORTRAITS = [
  {
    src: hero1,
    x: '13%',
    y: '51%',
    tilt: '-16deg',
    ink: '356 65% 66%',
  },
  {
    src: hero2,
    x: '29%',
    y: '19%',
    tilt: '12deg',
    ink: '30 74% 66%',
  },
  {
    src: hero3,
    x: '53%',
    y: '11%',
    tilt: '-8deg',
    ink: '205 37% 71%',
  },
  {
    src: hero4,
    x: '78%',
    y: '27%',
    tilt: '17deg',
    ink: '101 27% 63%',
  },
  {
    src: hero5,
    x: '87%',
    y: '63%',
    tilt: '-13deg',
    ink: '187 38% 66%',
  },
  {
    src: hero6,
    x: '30%',
    y: '79%',
    tilt: '19deg',
    ink: '41 60% 67%',
  },
] as const;

function Spellbook() {
  return (
    <svg viewBox="0 0 280 180" fill="none" className="empty-grimoire-book" aria-hidden="true">
      <ellipse cx="140" cy="158" rx="83" ry="10" fill="#060303" opacity=".45" />
      <path
        d="m29 58 108 24 114-25-9 85-102 27-105-27Z"
        fill="#521d25"
        stroke="#a14e50"
        strokeWidth="2"
      />
      <path d="m37 54 101 22 105-23-7 80-97 24-98-23Z" fill="#8f785a" stroke="#b79a70" />
      <path d="m42 47 95 22 101-22-6 81-93 22-93-22Z" fill="#d1b783" />
      <path
        d="M140 147C113 120 75 112 46 125L34 39c34-11 74-2 106 26Z"
        fill="#d9c398"
        stroke="#f0dab0"
      />
      <path
        d="M140 147c29-27 65-35 94-22l12-86c-34-11-74-2-106 26Z"
        fill="#bfa77d"
        stroke="#e4c99b"
      />
      <path d="M140 65v82" stroke="#70523e" strokeWidth="3" />
      <path
        d="M53 56c22-3 49 4 66 15M55 65c21-2 45 5 62 15M60 104c21 0 39 6 56 17M62 113c17 0 34 5 47 12M164 112c17-8 35-12 53-10M164 122c16-8 32-10 46-9"
        stroke="#7c6548"
        strokeWidth="2"
        strokeLinecap="round"
        opacity=".65"
      />
      <path d="m85 79 9 12-7 12-9-12Z" stroke="#8f483e" strokeWidth="2" />
      <circle cx="193" cy="75" r="17" stroke="#796346" />
      <path d="m193 58 5 12 12 5-12 5-5 12-5-12-12-5 12-5Z" stroke="#796346" />
      <path d="m149 139 7 26 6-8 9 3-10-28" fill="#983b43" stroke="#b85e61" />
      <path
        d="m30 58 5 11m210-12-5 12M40 131l2 7 14 4m180-11-2 7-14 4"
        stroke="#cfaa68"
        strokeWidth="3"
      />
    </svg>
  );
}

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

  return (
    <section className="empty-grimoire" aria-labelledby={titleId}>
      <div className="empty-grimoire-scene">
        <div className="empty-grimoire-art" aria-hidden="true">
          <div className="empty-grimoire-aura" />
          <svg
            className="empty-grimoire-orbits"
            viewBox="0 0 640 340"
            fill="none"
            aria-hidden="true"
          >
            <ellipse cx="320" cy="164" rx="220" ry="112" transform="rotate(-13 320 164)" />
            <ellipse
              cx="320"
              cy="164"
              rx="188"
              ry="134"
              transform="rotate(22 320 164)"
              strokeDasharray="2 12"
            />
            <path d="m116 91 3 8 8 3-8 3-3 8-3-8-8-3 8-3Zm390 151 3 8 8 3-8 3-3 8-3-8-8-3 8-3Z" />
          </svg>
          <Spellbook />
          {HERO_PORTRAITS.map((portrait, index) => (
            <div
              key={portrait.src}
              className="empty-grimoire-portrait"
              style={
                {
                  left: portrait.x,
                  top: portrait.y,
                  '--portrait-tilt': portrait.tilt,
                  '--portrait-ink': portrait.ink,
                  '--portrait-delay': `${index * 70}ms`,
                  '--float-delay': `${-index * 1.8}s`,
                } as CSSProperties
              }
            >
              <div className="empty-grimoire-portrait-face">
                <img src={portrait.src} alt="" width={256} height={256} draggable={false} />
              </div>
            </div>
          ))}
          <span className="empty-grimoire-mote empty-grimoire-mote--one" />
          <span className="empty-grimoire-mote empty-grimoire-mote--two" />
          <span className="empty-grimoire-mote empty-grimoire-mote--three" />
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
