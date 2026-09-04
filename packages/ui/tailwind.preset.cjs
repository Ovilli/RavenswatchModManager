/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ['class'],
  theme: {
    container: {
      center: true,
      padding: '1.5rem',
      screens: { '2xl': '1400px' },
    },
    extend: {
      colors: {
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))',
        },
        destructive: {
          DEFAULT: 'hsl(var(--destructive))',
          foreground: 'hsl(var(--destructive-foreground))',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))',
        },
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))',
        },
        popover: {
          DEFAULT: 'hsl(var(--popover))',
          foreground: 'hsl(var(--popover-foreground))',
        },
        card: {
          DEFAULT: 'hsl(var(--card))',
          foreground: 'hsl(var(--card-foreground))',
        },
        'surface-1': 'hsl(var(--surface-1))',
        'surface-2': 'hsl(var(--surface-2))',
        'text-primary': 'hsl(var(--text-primary))',
        'text-secondary': 'hsl(var(--text-secondary))',
        'text-tertiary': 'hsl(var(--text-tertiary))',
        pitch: 'hsl(var(--pitch))',
        oxblood: 'hsl(var(--oxblood))',
        crimson: 'hsl(var(--crimson))',
        char: 'hsl(var(--char))',
        ash: 'hsl(var(--ash))',
        smoke: 'hsl(var(--smoke))',
        parchment: 'hsl(var(--parchment))',
        gilt: 'hsl(var(--gilt))',
        moss: 'hsl(var(--moss))',
        frost: 'hsl(var(--frost))',
      },
      // One radius family, matching the CSS tokens. `DEFAULT` is overridden on
      // purpose: bare `rounded` is 42 uses in the desktop app and was landing
      // on Tailwind's 4px, a value nothing else in the design system uses.
      borderRadius: {
        DEFAULT: 'var(--radius-sm)',
        sm: 'var(--radius-sm)',
        md: 'var(--radius)',
        lg: 'calc(var(--radius) + 2px)',
      },
      // `text-crimson` (72 uses, mostly error copy) resolves to the bright
      // twin: the brand crimson is 2.16:1 on pitch, well under AA. Fills and
      // borders keep the deep colour.
      textColor: {
        crimson: 'hsl(var(--crimson-text))',
      },
      transitionTimingFunction: {
        'grimoire': 'cubic-bezier(0.4, 0, 0.2, 1)',
      },
      transitionDuration: {
        '150': '150ms',
      },
      keyframes: {
        'ink-stamp': {
          '0%': { opacity: '0.4', transform: 'scale(0.94)' },
          '60%': { opacity: '1', transform: 'scale(1.02)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
        'fade-in': {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
      },
      animation: {
        'ink-stamp': 'ink-stamp 150ms cubic-bezier(0.4, 0, 0.2, 1)',
        'fade-in': 'fade-in 200ms cubic-bezier(0.4, 0, 0.2, 1)',
      },
    },
  },
  plugins: [],
};
