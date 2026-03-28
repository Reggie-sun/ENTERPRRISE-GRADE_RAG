/**
 * 布局组件
 * 提供页面整体布局结构
 */

import type { ReactNode } from 'react';
import { BrandLogo } from './BrandLogo';

interface LayoutProps {
  children: ReactNode;  // 子组件。
}

export function Layout({ children }: LayoutProps) {
  return (
    // 主容器，设置相对定位和 z-index 确保内容在装饰性背景之上。
    <main className="relative z-10 w-full max-w-[1200px] min-[1232px]:max-w-[calc(100vw-32px)] mx-auto my-8 mb-12 px-4">
      <header className="mb-6 flex flex-wrap items-center justify-between gap-4 rounded-[28px] border border-[rgba(23,32,42,0.08)] bg-[rgba(255,255,255,0.62)] px-5 py-4 shadow-[0_12px_30px_rgba(77,42,16,0.08)] backdrop-blur-xl">
        <BrandLogo compact subtitle="智能知识与标准流程服务平台" />
        <div className="text-left sm:text-right">
          <p className="m-0 text-sm font-semibold text-ink">企业知识服务入口</p>
          <p className="m-0 mt-1 text-xs leading-relaxed text-ink-soft sm:text-sm">
            统一问答、资料查询、SOP 生成与管理服务
          </p>
        </div>
      </header>
      {children}
    </main>
  );
}
