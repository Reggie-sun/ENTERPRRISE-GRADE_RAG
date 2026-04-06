import type { ButtonHTMLAttributes, ReactNode } from 'react';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode;
  variant?: 'primary' | 'ghost';
  loading?: boolean;
}

export function Button({
  children,
  variant = 'primary',
  loading = false,
  disabled,
  className = '',
  ...props
}: ButtonProps) {
  const baseStyles = `
    border-0
    rounded-xl
    px-5 py-3
    font-bold
    cursor-pointer
    transition-all duration-150
    disabled:cursor-not-allowed
    disabled:opacity-50
  `;

  const variantStyles = variant === 'primary'
    ? `
        bg-gradient-to-br from-accent to-accent-deep
        text-white
        shadow-[0_2px_8px_rgba(194,65,12,0.15)]
        hover:not-disabled:shadow-[0_4px_12px_rgba(194,65,12,0.2)]
        hover:not-disabled:-translate-y-px
      `
    : `
        bg-[rgba(15,23,42,0.05)]
        text-ink
        border border-[rgba(15,23,42,0.06)]
        hover:not-disabled:bg-[rgba(15,23,42,0.08)]
        hover:not-disabled:border-[rgba(15,23,42,0.1)]
      `;

  return (
    <button
      className={`${baseStyles} ${variantStyles} ${className}`}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? '处理中...' : children}
    </button>
  );
}
