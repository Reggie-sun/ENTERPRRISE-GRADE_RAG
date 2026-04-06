/**
 * Input components - Enterprise grade
 */

import type { InputHTMLAttributes, TextareaHTMLAttributes } from 'react';

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
}

/** Single-line text input */
export function Input({ label, className = '', ...props }: InputProps) {
  const inputElement = (
    <input
      className={`
        w-full
        rounded-xl
        border border-[rgba(15,23,42,0.08)]
        bg-white
        px-4 py-3
        text-sm text-ink
        transition-all duration-150
        focus:outline-none
        focus:border-[rgba(194,65,12,0.4)]
        focus:ring-2 focus:ring-[rgba(194,65,12,0.08)]
        placeholder:text-ink-muted
        ${className}
      `}
      {...props}
    />
  );

  if (label) {
    return (
      <label className="grid gap-1.5 text-sm font-medium text-ink">
        {label}
        {inputElement}
      </label>
    );
  }

  return inputElement;
}

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
}

/** Multi-line textarea */
export function Textarea({ label, className = '', ...props }: TextareaProps) {
  const textareaElement = (
    <textarea
      className={`
        w-full min-h-28
        rounded-xl
        border border-[rgba(15,23,42,0.08)]
        bg-white
        px-4 py-3
        text-sm text-ink
        resize-y
        transition-all duration-150
        focus:outline-none
        focus:border-[rgba(194,65,12,0.4)]
        focus:ring-2 focus:ring-[rgba(194,65,12,0.08)]
        placeholder:text-ink-muted
        ${className}
      `}
      {...props}
    />
  );

  if (label) {
    return (
      <label className="grid gap-1.5 text-sm font-medium text-ink">
        {label}
        {textareaElement}
      </label>
    );
  }

  return textareaElement;
}
