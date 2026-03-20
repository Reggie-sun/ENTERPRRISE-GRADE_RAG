import { StrictMode } from 'react';  // 引入 React 严格模式，帮助发现潜在问题。
import { createRoot } from 'react-dom/client';  // 引入 React 18 的 createRoot API。
import './index.css';  // 引入全局样式文件。
import App from './App';  // 引入根组件。

// 创建 React 应用根节点并渲染。
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);