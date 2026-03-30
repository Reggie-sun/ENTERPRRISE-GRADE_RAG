import { StatusPill } from './StatusPill';

interface EvidenceSourceSummaryProps {
  retrievalStrategy?: string | null;
  ocrUsed?: boolean;
  parserName?: string | null;
  pageNo?: number | null;
  ocrConfidence?: number | null;
  qualityScore?: number | null;
}

const QUALITY_THRESHOLD = 0.55;

function formatPercent(value: number | null | undefined): string | null {
  if (value == null || Number.isNaN(value)) {
    return null;
  }
  return `${Math.round(value * 100)}%`;
}

function parserLabel(parserName: string | null | undefined): string | null {
  if (!parserName) {
    return null;
  }
  if (parserName.includes('docx_embedded_image_ocr')) {
    return 'Word 嵌图 OCR';
  }
  if (parserName.includes('pdf_ocr')) {
    return 'PDF OCR';
  }
  if (parserName.includes('image_ocr')) {
    return '图片 OCR';
  }
  if (parserName === 'document_preview') {
    return '文档预览回退';
  }
  if (parserName === 'docx_xml') {
    return 'Word 正文解析';
  }
  if (parserName === 'pdf_text') {
    return 'PDF 原生文本';
  }
  if (parserName === 'plain_text') {
    return '纯文本';
  }
  if (parserName === 'markdown_text') {
    return 'Markdown';
  }
  return parserName;
}

export function EvidenceSourceSummary({
  retrievalStrategy,
  ocrUsed = false,
  parserName,
  pageNo,
  ocrConfidence,
  qualityScore,
}: EvidenceSourceSummaryProps) {
  const readableParserLabel = parserLabel(parserName);
  const qualityPercent = formatPercent(qualityScore);
  const confidencePercent = formatPercent(ocrConfidence);
  const isLowQuality = qualityScore != null && qualityScore < QUALITY_THRESHOLD;
  const showSummary =
    ocrUsed || readableParserLabel !== null || retrievalStrategy === 'document_preview';

  if (!showSummary) {
    return null;
  }

  return (
    <div className="mt-3 rounded-2xl bg-[rgba(23,32,42,0.04)] px-4 py-3">
      <div className="flex flex-wrap gap-2">
        {ocrUsed ? <StatusPill tone={isLowQuality ? 'warn' : 'ok'}>OCR 证据</StatusPill> : null}
        {readableParserLabel ? <StatusPill tone="default">{readableParserLabel}</StatusPill> : null}
        {pageNo != null ? <StatusPill tone="default">第 {pageNo} 页</StatusPill> : null}
        {retrievalStrategy === 'document_preview' ? <StatusPill tone="warn">预览回退</StatusPill> : null}
        {qualityPercent ? <StatusPill tone={isLowQuality ? 'warn' : 'default'}>质量 {qualityPercent}</StatusPill> : null}
        {!qualityPercent && confidencePercent ? <StatusPill tone="default">置信度 {confidencePercent}</StatusPill> : null}
      </div>
      <p className="m-0 mt-3 text-sm leading-relaxed text-ink-soft">
        {ocrUsed
          ? isLowQuality
            ? '这条证据来自 OCR 识别，质量偏低。建议结合原文或原图继续复核。'
            : '这条证据来自 OCR 识别链路，适合结合原文页码回看。'
          : retrievalStrategy === 'document_preview'
            ? '这条证据来自文档预览回退，不是标准检索命中片段。'
            : '这条证据来自原生文本解析链路。'}
      </p>
    </div>
  );
}
