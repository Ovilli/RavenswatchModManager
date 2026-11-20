const preset = require('@rsmm/ui/tailwind-preset');

/** @type {import('tailwindcss').Config} */
module.exports = {
  presets: [preset],
  theme: {
    extend: {
      spacing: {
        app: 'var(--app-spacing)',
        'app-sm': 'var(--app-spacing-sm)',
      },
    },
  },
  content: ['./index.html', './src/**/*.{ts,tsx}', '../../packages/ui/src/**/*.{ts,tsx}'],
};
