/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#060a0f',
        surface: '#0c1420',
        surface2: '#111c2d',
        border: '#1a2840',
        accent: '#0dd9bb',
        'accent-dim': '#0aa88f',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
