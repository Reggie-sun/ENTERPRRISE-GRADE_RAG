import { defineConfig, loadEnv } from 'vite';  // 导入 Vite 配置定义函数和环境变量加载工具。
import react from '@vitejs/plugin-react';  // 导入 React 插件，支持 JSX 转换。
import path from 'path';  // 导入 path 模块，用于解析路径别名。

// Vite 配置对象。
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname, '');  // 加载 .env 中的前端变量。
  const apiTarget = env.VITE_API_TARGET || 'http://localhost:8020';  // 默认转发到本地后端 8020 端口。

  return {
    plugins: [react()],  // 启用 React 插件。
    resolve: {
      alias: {
        // 配置路径别名，@/ 指向 src/ 目录。
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      port: 3000,  // 开发服务器端口。
      proxy: {
        // 代理 API 请求到后端服务，避免跨域问题。
        '/api': {
          target: apiTarget,  // 后端服务地址，支持通过 VITE_API_TARGET 覆盖。
          changeOrigin: true,  // 修改请求头的 origin 字段。
        },
      },
    },
  };
});
