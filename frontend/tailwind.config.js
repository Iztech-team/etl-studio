/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: {
          DEFAULT: '#0a0a0f',
          50: '#f0f0f5',
          100: '#d8d8e8',
          200: '#a8a8c8',
          300: '#7878a8',
          400: '#484878',
          500: '#282848',
          600: '#181830',
          700: '#0f0f20',
          800: '#0a0a15',
          900: '#06060d',
        },
        acid: {
          DEFAULT: '#00ff88',
          dim: '#00cc66',
        },
        ember: {
          DEFAULT: '#ff6b35',
        },
        frost: {
          DEFAULT: '#4fc3f7',
        },
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', 'monospace'],
        sans: ['"DM Sans"', 'sans-serif'],
        display: ['"Space Mono"', 'monospace'],
      },
    },
  },
  plugins: [],
}
