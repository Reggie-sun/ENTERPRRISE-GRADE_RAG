/**
 * API 客户端
 * 封装所有后端 API 调用
 */

import type {
  HealthResponse,
  DocumentCreateResponse,
  DocumentUploadResponse,
  DocumentListResponse,
  DocumentDetailResponse,
  IngestJobStatusResponse,
  RetrievalRequest,
  RetrievalResponse,
  ChatRequest,
  ChatResponse,
} from './types';

// API 基础路径，与 Vite 代理配置对应。
const API_PREFIX = '/api/v1';

/** API 错误类，包含 HTTP 状态码和响应内容 */
class ApiError extends Error {
  constructor(
    public status: number,  // HTTP 状态码。
    public detail: string,  // 错误详情。
  ) {
    super(`API Error ${status}: ${detail}`);
    this.name = 'ApiError';
  }
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

  if (!isFormDataBody && !headers.has('Content-Type')) {  // 仅非 FormData 且未显式设置时才默认 JSON。
    headers.set('Content-Type', 'application/json');
  }

  // 发送请求。
  const response = await fetch(url, {
    ...options,
    headers,
  });

  // 解析响应内容。
  const contentType = response.headers.get('content-type') || '';
  const data = contentType.includes('application/json')
    ? await response.json()
    : await response.text();

  // 处理错误响应。
  if (!response.ok) {
    const detail = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
    throw new ApiError(response.status, detail);
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
export async function getDocuments(): Promise<DocumentListResponse> {
  return request<DocumentListResponse>('/documents');
}

/** 获取文档详情 */
export async function getDocument(docId: string): Promise<DocumentDetailResponse> {
  return request<DocumentDetailResponse>(`/documents/${encodeURIComponent(docId)}`);
}

/** 创建文档并排队入库（异步 Celery 任务） */
export async function createDocument(formData: FormData): Promise<DocumentCreateResponse> {
  const url = `${API_PREFIX}/documents`;

  const response = await fetch(url, {
    method: 'POST',
    body: formData,  // FormData 不需要设置 Content-Type，浏览器会自动设置。
  });

  const contentType = response.headers.get('content-type') || '';
  const data = contentType.includes('application/json')
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    const detail = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
    throw new ApiError(response.status, detail);
  }

  return data as DocumentCreateResponse;
}

/** 同步上传并入库文档 */
export async function uploadDocument(formData: FormData): Promise<DocumentUploadResponse> {
  const url = `${API_PREFIX}/documents/upload`;

  const response = await fetch(url, {
    method: 'POST',
    body: formData,
  });

  const contentType = response.headers.get('content-type') || '';
  const data = contentType.includes('application/json')
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    const detail = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
    throw new ApiError(response.status, detail);
  }

  return data as DocumentUploadResponse;
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

// 导出错误类，供组件使用。
export { ApiError };
