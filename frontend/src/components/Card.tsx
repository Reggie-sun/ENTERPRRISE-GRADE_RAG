/**
 * Card component - Professional elevation system
 */

import type { ReactNode } from 'react';

interface CardProps {
  children: ReactNode;
  className?: string;
}

export function Card({ children, className = '' }: CardProps) {
  return (
    <article
      className={`
        border border-[rgba(15,23,42,0.06)]
        bg-white
        rounded-2xl
        p-6
        shadow-[0_1px_3px_rgba(15,23,42,0.04)]
        transition-shadow duration-150
        ${className}
      `}
    >
      {children}
    </article>
  );
}

/** Hero card - larger, more prominent */
export function HeroCard({ children, className = '' }: CardProps) {
  return (
    <article
      className={`
        border border-[rgba(15,23,42,0.06)]
        bg-white
        rounded-2xl
        p-8
        shadow-[0_4px_12px_rgba(15,23,42,0.06),0_2px_4px_rgba(15,23,42,0.03)]
        ${className}
      `}
    >
      {children}
    </article>
  );
}
