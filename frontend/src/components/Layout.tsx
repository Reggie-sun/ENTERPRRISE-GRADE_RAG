/**
 * 布局组件
 * 提供页面整体布局结构
 */

import type { ReactNode } from 'react';

interface LayoutProps {
  children: ReactNode;  // 子组件。
}

export function Layout({ children }: LayoutProps) {
  return (
    // 主容器，设置相对定位和 z-index 确保内容在装饰性背景之上。
    <main className="relative z-10 mx-auto my-8 mb-12 w-full max-w-[1200px] px-4 min-[1232px]:max-w-[calc(100vw-32px)]">
      {children}
    </main>
  );
}
