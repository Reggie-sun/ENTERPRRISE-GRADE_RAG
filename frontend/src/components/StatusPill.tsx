/**
 * 状态徽章组件
 * 用于显示操作状态
 */

import type { ReactNode } from 'react';

interface StatusPillProps {
  children: ReactNode;  // 徽章内容。
  tone?: 'default' | 'ok' | 'warn' | 'error';  // 状态色调。
}

export function StatusPill({ children, tone = 'default' }: StatusPillProps) {
  // 根据状态选择背景色和文字色。
  const toneStyles = {
    default: 'bg-[rgba(23,32,42,0.06)]',  // 默认灰色。
    ok: 'bg-[rgba(31,122,82,0.11)] text-ok',  // 成功绿色。
    warn: 'bg-[rgba(141,93,22,0.12)] text-warn',  // 警告黄色。
    error: 'bg-[rgba(182,70,47,0.12)] text-accent-deep',  // 错误红色。
  };

  return (
    <div
      className={`
        inline-flex items-center gap-2
        min-h-9 w-fit
        px-3 py-2
        rounded-full
        text-sm font-bold
        ${toneStyles[tone]}
      `}
    >
      {children}
    </div>
  );
}