/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: ['./index.html', './404.html', './assets/js/**/*.js'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      colors: {
        app: 'var(--bg-app)', surface: 'var(--bg-surface)', elevated: 'var(--bg-elevated)',
        line: 'var(--border-color)', txt: 'var(--text-primary)', 'txt-2': 'var(--text-secondary)',
        'txt-3': 'var(--text-muted)',
        // canaux RGB → les modificateurs d'opacité (ring-accent/20…) fonctionnent
        accent: 'rgb(var(--accent-rgb) / <alpha-value>)',
        'accent-h': 'var(--accent-hover)', 'accent-s': 'var(--accent-soft)',
      },
    },
  },
  plugins: [],
};
