/**
 * Result display components
 */

import type { ReactNode } from 'react';

interface ResultBoxProps {
  children: ReactNode;
}

/** Result box - displays JSON or text results */
export function ResultBox({ children }: ResultBoxProps) {
  return (
    <div className="min-h-24 p-4 rounded-xl border border-dashed border-[rgba(15,23,42,0.1)] bg-[rgba(15,23,42,0.02)]">
      <pre className="m-0 whitespace-pre-wrap break-words font-mono text-sm leading-relaxed text-ink-soft">
        {children}
      </pre>
    </div>
  );
}

/** Result card - displays individual retrieval results */
interface ResultCardProps {
  title: string;
  meta?: { label: string; value: string }[];
  children: ReactNode;
  index?: number;
}

export function ResultCard({ title, meta = [], children, index }: ResultCardProps) {
  return (
    <article className="p-4 rounded-xl bg-white border border-[rgba(15,23,42,0.06)]">
      {/* Title */}
      <h3 className="m-0 mb-1.5 text-base font-semibold text-ink">
        {index !== undefined && `#${index + 1} `}{title}
      </h3>

      {/* Meta tags */}
      {meta.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-2.5 text-sm text-ink-soft">
          {meta.map((item, i) => (
            <span key={i} className="inline-flex items-center px-2 py-1 rounded-full bg-[rgba(15,23,42,0.04)]">
              {item.label} {item.value}
            </span>
          ))}
        </div>
      )}

      {/* Content */}
      <div className="text-ink text-sm leading-relaxed">{children}</div>
    </article>
  );
}
