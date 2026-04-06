/**
 * Status Pill - Clear state indication
 */

import type { ReactNode } from 'react';

interface StatusPillProps {
  children: ReactNode;
  tone?: 'default' | 'ok' | 'warn' | 'error';
}

export function StatusPill({ children, tone = 'default' }: StatusPillProps) {
  const toneStyles = {
    default: 'bg-[rgba(15,23,42,0.06)] text-ink-soft',
    ok: 'bg-[#d1fae5] text-[#059669]',
    warn: 'bg-[#fef3c7] text-[#d97706]',
    error: 'bg-[#fee2e2] text-[#dc2626]',
  };

  return (
    <div
      className={`
        inline-flex items-center gap-2
        min-h-8 w-fit
        px-3 py-1.5
        rounded-full
        text-xs font-semibold
        tracking-wide
        ${toneStyles[tone]}
      `}
    >
      {children}
    </div>
  );
}
