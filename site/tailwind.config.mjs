/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{astro,html,js,jsx,ts,tsx,md,mdx}'],
  theme: {
    extend: {
      fontFamily: {
        serif: [
          'Iowan Old Style',
          'Palatino Linotype',
          'URW Palladio L',
          'P052',
          'Palatino',
          'serif',
        ],
        sans: [
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'BlinkMacSystemFont',
          'Segoe UI',
          'Inter',
          'Helvetica',
          'Arial',
          'sans-serif',
        ],
        mono: [
          'ui-monospace',
          'SFMono-Regular',
          'Menlo',
          'Monaco',
          'Consolas',
          'monospace',
        ],
      },
      colors: {
        ink: {
          DEFAULT: '#111418',
          muted: '#4a5160',
          faint: '#7a8192',
        },
        paper: {
          DEFAULT: '#fbfaf7',
          alt: '#f3f1ec',
        },
        accent: {
          DEFAULT: '#1f3a93',
          soft: '#e4ebf7',
        },
      },
      maxWidth: {
        'prose-wide': '72rem',
      },
    },
  },
  plugins: [],
};
