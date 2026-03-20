/**
 * 结果展示组件
 * 用于显示 API 返回的结果
 */

import type { ReactNode } from 'react';

interface ResultBoxProps {
  children: ReactNode;  // 结果内容。
}

/** 结果展示框 - 用于显示 JSON 或文本结果 */
export function ResultBox({ children }: ResultBoxProps) {
  return (
    <div className="min-h-24 p-4 rounded-xl border border-dashed border-[rgba(23,32,42,0.14)] bg-[rgba(255,255,255,0.55)]">
      <pre className="m-0 whitespace-pre-wrap break-words font-mono text-sm leading-relaxed text-ink">
        {children}
      </pre>
    </div>
  );
}

/** 结果卡片 - 用于显示单条检索结果或引用 */
interface ResultCardProps {
  title: string;  // 标题。
  meta?: { label: string; value: string }[];  // 元数据标签。
  children: ReactNode;  // 内容。
  index?: number;  // 序号。
}

export function ResultCard({ title, meta = [], children, index }: ResultCardProps) {
  return (
    <article className="p-4 rounded-xl bg-[rgba(255,255,255,0.7)] border border-[rgba(23,32,42,0.08)]">
      {/* 标题 */}
      <h3 className="m-0 mb-1.5 text-base font-semibold text-ink">
        {index !== undefined && `#${index + 1} `}{title}
      </h3>

      {/* 元数据标签 */}
      {meta.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-2.5 text-sm text-ink-soft">
          {meta.map((item, i) => (
            <span key={i} className="inline-flex items-center px-2 py-1 rounded-full bg-[rgba(23,32,42,0.06)]">
              {item.label} {item.value}
            </span>
          ))}
        </div>
      )}

      {/* 内容 */}
      <div className="text-ink text-sm leading-relaxed">{children}</div>
    </article>
  );
}