/** @type {import('tailwindcss').Config} */  // Tailwind CSS 配置类型注释。
export default {
  content: [
    "./index.html",  // 扫描 index.html 中的类名。
    "./src/**/*.{js,ts,jsx,tsx}",  // 扫描 src 目录下所有 JS/TS/JSX/TSX 文件。
  ],
  theme: {
    extend: {
      // 自定义颜色变量，与原 demo.html 保持一致。
      colors: {
        bg: '#f5efe4',  // 主背景色。
        'bg-soft': 'rgba(255, 255, 255, 0.72)',  // 柔和背景色。
        panel: 'rgba(255, 250, 244, 0.86)',  // 面板背景色。
        ink: '#17202a',  // 主文字颜色。
        'ink-soft': '#56616d',  // 柔和文字颜色。
        accent: '#b6462f',  // 强调色。
        'accent-deep': '#7f2f1f',  // 深强调色。
        'accent-warm': '#f6d3ae',  // 暖强调色。
        ok: '#1f7a52',  // 成功状态颜色。
        warn: '#8d5d16',  // 警告状态颜色。
      },
      // 自定义阴影。
      boxShadow: {
        'soft': '0 24px 60px rgba(77, 42, 16, 0.14)',  // 柔和阴影。
      },
      // 自定义圆角。
      borderRadius: {
        '4xl': '2rem',  // 更大的圆角。
      },
    },
  },
  plugins: [],  // 暂不使用额外插件。
}