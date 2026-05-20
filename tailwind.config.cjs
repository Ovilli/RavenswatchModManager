const preset = require('./packages/ui/tailwind.preset.cjs');

/** @type {import('tailwindcss').Config} */
module.exports = {
  presets: [preset],
  content: [
    './app/**/*.{ts,tsx}',
    './apps/www/src/**/*.{ts,tsx}',
    './packages/ui/src/**/*.{ts,tsx}',
  ],
};
