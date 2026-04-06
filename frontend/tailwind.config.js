/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: '#f8fafc',
        'bg-soft': 'rgba(255, 255, 255, 0.92)',
        panel: 'rgba(255, 255, 255, 0.96)',
        ink: '#0f172a',
        'ink-soft': '#64748b',
        'ink-muted': '#94a3b8',
        line: 'rgba(15, 23, 42, 0.06)',
        'line-strong': 'rgba(15, 23, 42, 0.12)',
        accent: '#c2410c',
        'accent-deep': '#9a2d0c',
        'accent-light': '#fef3f0',
        'accent-warm': '#fdebd0',
        ok: '#059669',
        'ok-light': '#d1fae5',
        warn: '#d97706',
        'warn-light': '#fef3c7',
        error: '#dc2626',
        'error-light': '#fee2e2',
      },
      boxShadow: {
        soft: '0 24px 60px rgba(77, 42, 16, 0.14)',
        sm: '0 1px 2px rgba(15, 23, 42, 0.04)',
        md: '0 4px 12px rgba(15, 23, 42, 0.06), 0 2px 4px rgba(15, 23, 42, 0.03)',
        lg: '0 12px 28px rgba(15, 23, 42, 0.08), 0 4px 10px rgba(15, 23, 42, 0.04)',
        xl: '0 20px 40px rgba(15, 23, 42, 0.1), 0 8px 16px rgba(15, 23, 42, 0.05)',
      },
      borderRadius: {
        '4xl': '2rem',
      },
    },
  },
  plugins: [],
}
