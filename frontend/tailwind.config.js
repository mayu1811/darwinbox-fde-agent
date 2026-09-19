/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: {
          950: '#0a0d14',
          900: '#0f131c',
          850: '#151a25',
          800: '#1c2230',
          700: '#2a3242',
          600: '#3b4558',
          500: '#5a6478',
          400: '#8b94a8',
          300: '#b6bdcc',
          200: '#dbe1ec',
          100: '#eef1f6',
        },
        accent: {
          DEFAULT: '#5b8def',
          soft: '#1e2a45',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      keyframes: {
        'fade-in': { '0%': { opacity: '0', transform: 'translateY(4px)' }, '100%': { opacity: '1', transform: 'none' } },
        'pulse-ring': { '0%': { boxShadow: '0 0 0 0 rgba(91,141,239,0.45)' }, '100%': { boxShadow: '0 0 0 10px rgba(91,141,239,0)' } },
      },
      animation: {
        'fade-in': 'fade-in 0.25s ease-out',
        'pulse-ring': 'pulse-ring 1.6s ease-out infinite',
      },
    },
  },
  plugins: [],
}
