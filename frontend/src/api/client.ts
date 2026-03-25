/**
 * API 客户端
 * 封装所有后端 API 调用
 */

import type {
  HealthResponse,
  DocumentCreateResponse,
  DocumentUploadResponse,
  DocumentListResponse,
  DocumentListQuery,
  DocumentDetailResponse,
  DocumentPreviewResponse,
  IngestJobStatusResponse,
  RetrievalRequest,
  RetrievalResponse,
  ChatRequest,
  ChatResponse,
} from './types';

// API 基础路径，与 Vite 代理配置对应。
const API_PREFIX = '/api/v1';
const REQUEST_TIMEOUT_MS = 20_000;  // 前端请求超时时间，避免页面无限等待。

type ApiErrorKind = 'http' | 'network' | 'timeout' | 'parse';

export interface ChatStreamMeta {
  question: string;
  mode: string;
  model: string;
  citations: ChatResponse['citations'];
}

export interface ChatStreamHandlers {
  onMeta?: (meta: ChatStreamMeta) => void;
  onDelta?: (delta: string) => void;
  onDone?: (response: ChatResponse) => void;
}

function toText(value: unknown): string {
  if (typeof value === 'string') {
    return value;
  }
  if (value === null || value === undefined) {
    return '';
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function extractDetail(payload: unknown): string {
  if (typeof payload === 'string') {
    return payload;
  }
  if (payload && typeof payload === 'object' && 'detail' in payload) {
    const detail = (payload as { detail?: unknown }).detail;
    return toText(detail) || toText(payload);
  }
  return toText(payload);
}

/** API 错误类，包含 HTTP 状态码和响应内容 */
class ApiError extends Error {
  constructor(
    public kind: ApiErrorKind,  // 错误类型，区分网络、超时、HTTP 错误。
    public detail: string,  // 错误详情。
    public status?: number,  // HTTP 状态码（仅 HTTP 错误可用）。
    public payload?: unknown,  // 原始错误响应体，供页面层做定制解析。
  ) {
    const suffix = status ? ` ${status}` : '';
    super(`API Error${suffix}: ${detail}`);
    this.name = 'ApiError';
  }
}

export function formatApiError(error: unknown, context: string): string {
  if (error instanceof ApiError) {
    if (error.kind === 'timeout') {
      return `${context}超时（${Math.floor(REQUEST_TIMEOUT_MS / 1000)}s），请检查后端服务或网络后重试。`;
    }
    if (error.kind === 'network') {
      return `${context}失败：无法连接后端接口，请确认 FastAPI 是否已启动且前端代理配置正确。`;
    }
    if (error.kind === 'http') {
      if (error.status === 502 || error.status === 503 || error.status === 504) {
        return `${context}失败：后端依赖未就绪或不可达（HTTP ${error.status}）。${error.detail}`;
      }
      return `${context}失败（HTTP ${error.status ?? 'unknown'}）：${error.detail}`;
    }
    if (error.kind === 'parse') {
      return `${context}失败：后端响应解析异常，请检查接口返回格式。`;
    }
  }
  if (error instanceof Error) {
    return `${context}失败：${error.message}`;
  }
  return `${context}失败：${String(error)}`;
}

/**
 * 通用请求函数
 * @param path API 路径（不含前缀）
 * @param options fetch 选项
 * @returns 解析后的 JSON 响应
 */
async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_PREFIX}${path}`;
  const headers = new Headers(options.headers);  // 统一标准化请求头，兼容对象/数组/Headers 三种输入。
  const isFormDataBody = options.body instanceof FormData;  // FormData 由浏览器自动注入 multipart boundary。
  const controller = new AbortController();  // 为请求加可控超时。
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  if (!isFormDataBody && !headers.has('Content-Type')) {  // 仅非 FormData 且未显式设置时才默认 JSON。
    headers.set('Content-Type', 'application/json');
  }

  let response: Response;
  try {
    // 发送请求。
    response = await fetch(url, {
      ...options,
      headers,
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw new ApiError('timeout', `Request timeout: ${path}`);
    }
    throw new ApiError('network', `Network error: ${path}`);
  } finally {
    clearTimeout(timeout);
  }

  let data: unknown;
  try {
    // 解析响应内容。
    const contentType = response.headers.get('content-type') || '';
    data = contentType.includes('application/json')
      ? await response.json()
      : await response.text();
  } catch {
    throw new ApiError('parse', `Failed to parse response: ${path}`);
  }

  // 处理错误响应。
  if (!response.ok) {
    const detail = extractDetail(data);
    throw new ApiError('http', detail, response.status, data);
  }

  return data as T;
}

// ========== 健康检查 API ==========

/** 获取后端健康状态 */
export async function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/health');
}

// ========== 文档 API ==========

/** 获取文档列表 */
export async function getDocuments(query: DocumentListQuery = {}): Promise<DocumentListResponse> {
  const params = new URLSearchParams();  // 统一组装查询参数，避免手写字符串拼接错误。
  if (query.page !== undefined) {
    params.set('page', String(query.page));
  }
  if (query.page_size !== undefined) {
    params.set('page_size', String(query.page_size));
  }
  if (query.keyword) {
    params.set('keyword', query.keyword);
  }
  if (query.department_id) {
    params.set('department_id', query.department_id);
  }
  if (query.category_id) {
    params.set('category_id', query.category_id);
  }
  if (query.status) {
    params.set('status', query.status);
  }
  const suffix = params.toString();  // 生成最终 query string。
  const path = suffix ? `/documents?${suffix}` : '/documents';
  return request<DocumentListResponse>(path);
}

/** 获取文档详情 */
export async function getDocument(docId: string): Promise<DocumentDetailResponse> {
  return request<DocumentDetailResponse>(`/documents/${encodeURIComponent(docId)}`);
}

/** 获取文档预览 */
export async function getDocumentPreview(docId: string, maxChars = 12000): Promise<DocumentPreviewResponse> {
  const params = new URLSearchParams();
  params.set('max_chars', String(maxChars));
  return request<DocumentPreviewResponse>(`/documents/${encodeURIComponent(docId)}/preview?${params.toString()}`);
}

/** 创建文档并排队入库（异步 Celery 任务） */
export async function createDocument(formData: FormData): Promise<DocumentCreateResponse> {
  return request<DocumentCreateResponse>('/documents', {
    method: 'POST',
    body: formData,  // FormData 不需要设置 Content-Type，浏览器会自动设置 boundary。
  });
}

/** 同步上传并入库文档 */
export async function uploadDocument(formData: FormData): Promise<DocumentUploadResponse> {
  return request<DocumentUploadResponse>('/documents/upload', {
    method: 'POST',
    body: formData,
  });
}

// ========== Ingest Job API ==========

/** 获取任务状态 */
export async function getIngestJobStatus(jobId: string): Promise<IngestJobStatusResponse> {
  return request<IngestJobStatusResponse>(`/ingest/jobs/${encodeURIComponent(jobId)}`);
}

/** 手动触发任务执行 */
export async function runIngestJob(jobId: string): Promise<IngestJobStatusResponse> {
  return request<IngestJobStatusResponse>(`/ingest/jobs/${encodeURIComponent(jobId)}/run`, {
    method: 'POST',
  });
}

// ========== 检索 API ==========

/** 执行文档检索 */
export async function searchDocuments(req: RetrievalRequest): Promise<RetrievalResponse> {
  return request<RetrievalResponse>('/retrieval/search', {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

// ========== 问答 API ==========

/** 发起问答请求 */
export async function askQuestion(req: ChatRequest): Promise<ChatResponse> {
  return request<ChatResponse>('/chat/ask', {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

/** 发起流式问答请求（SSE） */
export async function askQuestionStream(req: ChatRequest, handlers: ChatStreamHandlers = {}): Promise<ChatResponse> {
  const controller = new AbortController();  // 复用统一超时逻辑，避免流式请求悬挂。
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  let response: Response;
  try {
    response = await fetch(`${API_PREFIX}/chat/ask/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw new ApiError('timeout', 'Request timeout: /chat/ask/stream');
    }
    throw new ApiError('network', 'Network error: /chat/ask/stream');
  }

  if (!response.ok) {
    let payload: unknown = null;
    try {
      const contentType = response.headers.get('content-type') || '';
      payload = contentType.includes('application/json') ? await response.json() : await response.text();
    } catch {
      throw new ApiError('parse', 'Failed to parse stream error payload: /chat/ask/stream');
    } finally {
      clearTimeout(timeout);
    }
    throw new ApiError('http', extractDetail(payload), response.status, payload);
  }

  if (!response.body) {
    clearTimeout(timeout);
    throw new ApiError('parse', 'Stream body is empty: /chat/ask/stream');
  }

  const decoder = new TextDecoder();  // 用 TextDecoder 把 Uint8Array 片段转成字符串。
  const reader = response.body.getReader();  // 读取 ReadableStream 数据片段。
  let buffer = '';  // 累积尚未完整成帧的数据。
  let finalResponse: ChatResponse | null = null;  // done 事件会覆盖这个对象。
  let partialAnswer = '';  // 没有 done 事件时，兜底返回增量拼接结果。
  let latestMeta: ChatStreamMeta | null = null;  // 保留最近一次 meta，供兜底组装响应。

  const handleFrame = (frame: string) => {  // 解析单个 SSE 帧并分发事件。
    const lines = frame
      .split('\n')
      .map((line) => line.trim())
      .filter((line) => line.length > 0);
    if (lines.length === 0) {
      return;
    }

    let eventName = '';
    const dataLines: string[] = [];
    for (const line of lines) {
      if (line.startsWith('event:')) {
        eventName = line.slice('event:'.length).trim();
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice('data:'.length).trim());
      }
    }

    if (!eventName || dataLines.length === 0) {
      return;
    }

    let payload: unknown;
    try {
      payload = JSON.parse(dataLines.join('\n'));
    } catch {
      return;  // 非法 payload 直接忽略，避免整条流中断。
    }

    if (eventName === 'meta') {
      latestMeta = payload as ChatStreamMeta;
      handlers.onMeta?.(latestMeta);
      return;
    }
    if (eventName === 'answer_delta') {
      const delta = (payload as { delta?: unknown }).delta;
      if (typeof delta === 'string' && delta) {
        partialAnswer += delta;
        handlers.onDelta?.(delta);
      }
      return;
    }
    if (eventName === 'done') {
      finalResponse = payload as ChatResponse;
      handlers.onDone?.(finalResponse);
      return;
    }
    if (eventName === 'error') {
      const detail = (payload as { message?: unknown }).message;
      throw new ApiError('http', typeof detail === 'string' ? detail : 'Unknown stream error');
    }
  };

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split('\n\n');  // SSE 事件之间以空行分隔。
      buffer = frames.pop() ?? '';  // 留下最后一个不完整帧，等待下一次拼接。
      for (const frame of frames) {
        handleFrame(frame);
      }
    }
    buffer += decoder.decode();  // flush decoder，避免尾部 UTF-8 字节丢失。
    if (buffer.trim()) {  // 处理最后一个可能完整但未被分隔的帧。
      handleFrame(buffer);
    }
  } finally {
    clearTimeout(timeout);
    reader.releaseLock();
  }

  if (finalResponse) {
    return finalResponse;
  }
  const fallbackMeta = latestMeta as ChatStreamMeta | null;  // 显式保留元数据类型，避免 TS 把分支收窄成 never。
  if (fallbackMeta) {  // 服务端未返回 done 时，兜底组装一个可消费结果，避免前端报错。
    return {
      question: fallbackMeta.question,
      answer: partialAnswer,
      mode: fallbackMeta.mode,
      model: fallbackMeta.model,
      citations: fallbackMeta.citations,
    };
  }
  throw new ApiError('parse', 'No valid stream events were received: /chat/ask/stream');
}

// 导出错误类，供组件使用。
export { ApiError };
