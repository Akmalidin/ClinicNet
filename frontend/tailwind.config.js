/** @type {import('tailwindcss').Config} */
// Tokens ported from Akmalidin/dental (frontend/tailwind.config.js) for
// visual continuity between the two products — not a dependency on that
// repo, just the same palette/typography values copied in.
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts}'],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: '#2563EB',
          dark: '#1D4ED8',
          light: '#DBEAFE',
        },
        accent: '#10B981',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [require('@tailwindcss/forms')],
}
