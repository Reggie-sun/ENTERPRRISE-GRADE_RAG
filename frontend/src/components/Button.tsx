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
    rounded-full
    px-5 py-3
    font-bold
    cursor-pointer
    transition-all duration-200
    disabled:cursor-wait
    disabled:opacity-70
  `;

  const variantStyles = variant === 'primary'
    ? `
        bg-gradient-to-br from-accent to-[#d16837]
        text-white
        shadow-[0_18px_28px_rgba(182,70,47,0.24)]
        hover:not-disabled:-translate-y-0.5
      `
    : `
        bg-[rgba(23,32,42,0.06)]
        text-ink
        hover:not-disabled:-translate-y-0.5
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