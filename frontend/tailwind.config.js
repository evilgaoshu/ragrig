/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: '#2F6FEB',
        ink: '#111827',
        muted: '#667085',
        line: '#D8E2F3',
        canvas: '#F3F7FE',
        panel: '#FFFFFF',
      },
    },
  },
  plugins: [],
}
