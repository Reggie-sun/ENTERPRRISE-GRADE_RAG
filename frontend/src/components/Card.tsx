/**
 * 卡片组件
 * 用于包裹各功能模块的面板
 */

import type { ReactNode } from 'react';

interface CardProps {
  children: ReactNode;  // 子组件。
  className?: string;  // 额外的类名。
}

export function Card({ children, className = '' }: CardProps) {
  return (
    <article
      className={`
        border border-line  /* 边框 */
        bg-bg-soft  /* 柔和背景 */
        backdrop-blur-xl  /* 毛玻璃效果 */
        rounded-3xl  /* 大圆角 */
        p-6  /* 内边距 */
        shadow-soft  /* 柔和阴影 */
        ${className}
      `}
    >
      {children}
    </article>
  );
}

/** Hero 卡片 - 用于顶部展示区 */
export function HeroCard({ children, className = '' }: CardProps) {
  return (
    <article
      className={`
        border border-line
        bg-bg-soft
        backdrop-blur-xl
        rounded-4xl  /* 更大的圆角 */
        p-7
        shadow-soft
        ${className}
      `}
    >
      {children}
    </article>
  );
}