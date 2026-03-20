/**
 * 输入框组件
 * 提供文本输入和文本域两种类型
 */

import type { InputHTMLAttributes, TextareaHTMLAttributes } from 'react';

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;  // 标签文本。
}

/** 单行文本输入框 */
export function Input({ label, className = '', ...props }: InputProps) {
  const inputElement = (
    <input
      className={`
        w-full
        rounded-2xl
        border border-[rgba(23,32,42,0.12)]
        bg-[rgba(255,255,255,0.82)]
        px-4 py-3
        text-ink
        transition-all duration-200
        focus:outline-none
        focus:border-[rgba(182,70,47,0.48)]
        focus:-translate-y-0.5
        placeholder:text-ink-soft
        ${className}
      `}
      {...props}
    />
  );

  // 如果有标签，包裹在 label 元素中。
  if (label) {
    return (
      <label className="grid gap-1.5 text-sm font-semibold">
        {label}
        {inputElement}
      </label>
    );
  }

  return inputElement;
}

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;  // 标签文本。
}

/** 多行文本输入框 */
export function Textarea({ label, className = '', ...props }: TextareaProps) {
  const textareaElement = (
    <textarea
      className={`
        w-full min-h-28
        rounded-2xl
        border border-[rgba(23,32,42,0.12)]
        bg-[rgba(255,255,255,0.82)]
        px-4 py-3
        text-ink
        resize-y
        transition-all duration-200
        focus:outline-none
        focus:border-[rgba(182,70,47,0.48)]
        focus:-translate-y-0.5
        placeholder:text-ink-soft
        ${className}
      `}
      {...props}
    />
  );

  // 如果有标签，包裹在 label 元素中。
  if (label) {
    return (
      <label className="grid gap-1.5 text-sm font-semibold">
        {label}
        {textareaElement}
      </label>
    );
  }

  return textareaElement;
}