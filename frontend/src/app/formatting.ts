/**
 * 可为空的值统一渲染为 '-' 或字符串
 */
export function renderNullable(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') {
    return '-';
  }
  return String(value);
}

/**
 * 秒数格式化为可读时长
 */
export function formatAgeSeconds(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return '-';
  }
  if (value < 60) {
    return `${value}s`;
  }
  const minutes = Math.floor(value / 60);
  const seconds = value % 60;
  if (minutes < 60) {
    return `${minutes}m ${seconds}s`;
  }
  const hours = Math.floor(minutes / 60);
  const remainMinutes = minutes % 60;
  return `${hours}h ${remainMinutes}m`;
}

/**
 * ISO 时间字符串格式化为本地时间
 */
export function formatLocalTime(value: string | null): string {
  if (!value) {
    return '-';
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString('zh-CN', { hour12: false });
}
