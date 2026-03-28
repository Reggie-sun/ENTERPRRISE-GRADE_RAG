interface BrandLogoProps {
  compact?: boolean;
  className?: string;
  subtitle?: string;
}

export function BrandLogo({ compact = false, className = '', subtitle }: BrandLogoProps) {
  const wordmarkClass = compact
    ? 'text-[1.75rem] sm:text-[2rem] tracking-[0.18em]'
    : 'text-[2.6rem] sm:text-[3rem] tracking-[0.2em]';
  const subtitleClass = compact ? 'text-sm sm:text-base' : 'text-lg sm:text-xl';
  const markClass = compact ? 'h-7 w-7 sm:h-8 sm:w-8' : 'h-10 w-10 sm:h-12 sm:w-12';

  return (
    <div className={`inline-flex flex-col ${className}`.trim()} aria-label="WELLI 伟立机器人">
      <div className="inline-flex items-end gap-2 sm:gap-3">
        <span className={`${wordmarkClass} font-black leading-none text-[#3c4348]`}>
          WELLI
        </span>
        <span className={`relative inline-block ${markClass}`}>
          <span className="absolute left-0 top-1/2 h-[24%] w-[72%] -translate-y-1/2 rounded-full bg-[#f29100]" />
          <span className="absolute right-0 top-0 h-full w-[24%] rounded-full bg-[#f29100]" />
        </span>
      </div>
      <span className={`${subtitleClass} mt-2 font-black tracking-[0.12em] text-[#3c4348]`}>
        伟立机器人
      </span>
      {subtitle ? (
        <span className="mt-2 text-xs leading-relaxed text-ink-soft sm:text-sm">
          {subtitle}
        </span>
      ) : null}
    </div>
  );
}
