/**
 * API 客户端
 * 封装所有后端 API 调用
 */

import type {
  HealthResponse,
  LoginRequest,
  LoginResponse,
  LogoutResponse,
  AuthProfileResponse,
  IdentityBootstrapResponse,
  EventLogListQuery,
  EventLogListResponse,
  OpsSummaryResponse,
  RequestSnapshotReplayRequest,
  RequestSnapshotReplayResponse,
  SystemConfigResponse,
  SystemConfigUpdateRequest,
  SopListQuery,
  SopListResponse,
  SopDetailResponse,
  SopPreviewResponse,
  SopGenerateByScenarioRequest,
  SopGenerateByDocumentRequest,
  SopGenerateByTopicRequest,
  SopDraftExportRequest,
  SopGenerationDraftResponse,
  SopSaveRequest,
  SopSaveResponse,
  SopVersionDetailResponse,
  SopVersionListResponse,
  DocumentCreateResponse,
  DocumentBatchCreateResponse,
  DocumentUploadResponse,
  DocumentListResponse,
  DocumentListQuery,
  DocumentDetailResponse,
  DocumentDeleteResponse,
  DocumentBatchDeleteResponse,
  DocumentBatchRebuildResponse,
  DocumentBatchRestoreResponse,
  DocumentPreviewResponse,
  DocumentRebuildResponse,
  IngestJobStatusResponse,
  RerankCanaryListResponse,
  RetrievalRerankCompareResponse,
  RetrievalRequest,
  RetrievalResponse,
  ChatRequest,
  ChatResponse,
} from './types';

// API 基础路径，与 Vite 代理配置对应。
const API_PREFIX = '/api/v1';
const REQUEST_TIMEOUT_MS = 20_000;  // 前端请求超时时间，避免页面无限等待。
const OPS_SUMMARY_TIMEOUT_MS = 60_000;  // 运行态汇总会聚合健康检查、日志和快照，允许更长超时预算。
const STREAM_IDLE_TIMEOUT_MS = 120_000;  // 流式接口允许更长空闲时间，避免首包或慢模型被固定 20s 误杀。

type ApiErrorKind = 'http' | 'network' | 'timeout' | 'parse';
type UnauthorizedListener = (detail: string) => void;

let accessToken: string | null = null;
let unauthorizedListener: UnauthorizedListener | null = null;

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

export interface StreamRequestOptions {
  signal?: AbortSignal;
}

export interface SopGenerationStreamMeta {
  request_mode: SopGenerationDraftResponse['request_mode'];
  generation_mode: SopGenerationDraftResponse['generation_mode'];
  title: SopGenerationDraftResponse['title'];
  department_id: SopGenerationDraftResponse['department_id'];
  department_name: SopGenerationDraftResponse['department_name'];
  process_name: SopGenerationDraftResponse['process_name'];
  scenario_name: SopGenerationDraftResponse['scenario_name'];
  topic: SopGenerationDraftResponse['topic'];
  model: SopGenerationDraftResponse['model'];
  citations: SopGenerationDraftResponse['citations'];
}

export interface SopGenerationStreamHandlers {
  onMeta?: (meta: SopGenerationStreamMeta) => void;
  onDelta?: (delta: string) => void;
  onDone?: (response: SopGenerationDraftResponse) => void;
}

function extractFilenameFromDisposition(disposition: string | null, fallback: string): string {
  if (!disposition) {
    return fallback;
  }
  const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch {
      return utf8Match[1];
    }
  }
  const filenameMatch = disposition.match(/filename="?([^";]+)"?/i);
  return filenameMatch?.[1] || fallback;
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

function createAbortTimeout(controller: AbortController, timeoutMs: number) {
  let timeout: ReturnType<typeof setTimeout> | null = null;

  const touch = () => {
    if (timeout !== null) {
      clearTimeout(timeout);
    }
    timeout = setTimeout(() => controller.abort(), timeoutMs);
  };

  const clear = () => {
    if (timeout !== null) {
      clearTimeout(timeout);
      timeout = null;
    }
  };

  touch();
  return { touch, clear };
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
export class ApiError extends Error {
  constructor(
    public kind: ApiErrorKind,  // 错误类型，区分网络、超时、HTTP 错误。
    public detail: string,  // 错误详情。
    public status?: number,  // HTTP 状态码（仅 HTTP 错误可用）。
    public payload?: unknown,  // 原始错误响应体，供页面层做定制解析。
    public timeoutMs?: number,  // 仅 timeout 时记录实际超时预算，便于页面提示准确展示。
  ) {
    const suffix = status ? ` ${status}` : '';
    super(`API Error${suffix}: ${detail}`);
    this.name = 'ApiError';
  }
}

export function setApiAccessToken(token: string | null) {
  accessToken = token?.trim() || null;
}

export function onApiUnauthorized(listener: UnauthorizedListener | null) {
  unauthorizedListener = listener;
  return () => {
    if (unauthorizedListener === listener) {
      unauthorizedListener = null;
    }
  };
}

export function formatApiError(error: unknown, context: string): string {
  if (error instanceof ApiError) {
    if (error.kind === 'timeout') {
      const timeoutSeconds = Math.max(1, Math.floor((error.timeoutMs ?? REQUEST_TIMEOUT_MS) / 1000));
      return `${context}超时（${timeoutSeconds}s），请检查后端服务或网络后重试。`;
    }
    if (error.kind === 'network') {
      return `${context}失败：无法连接后端接口，请确认 FastAPI 是否已启动且前端代理配置正确。`;
    }
    if (error.kind === 'http') {
      if (!error.status) {
        return `${context}失败：${error.detail}`;
      }
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
  return requestWithTimeout<T>(path, REQUEST_TIMEOUT_MS, options);
}

async function requestWithTimeout<T>(path: string, timeoutMs: number, options: RequestInit = {}): Promise<T> {
  const url = `${API_PREFIX}${path}`;
  const headers = new Headers(options.headers);  // 统一标准化请求头，兼容对象/数组/Headers 三种输入。
  const isFormDataBody = options.body instanceof FormData;  // FormData 由浏览器自动注入 multipart boundary。
  const controller = new AbortController();  // 为请求加可控超时。
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  const externalSignal = options.signal;
  const handleExternalAbort = () => controller.abort();

  if (externalSignal) {
    if (externalSignal.aborted) {
      controller.abort();
    } else {
      externalSignal.addEventListener('abort', handleExternalAbort, { once: true });
    }
  }

  if (accessToken && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${accessToken}`);
  }

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
      throw new ApiError('timeout', `Request timeout: ${path}`, undefined, undefined, timeoutMs);
    }
    throw new ApiError('network', `Network error: ${path}`);
  } finally {
    clearTimeout(timeout);
    externalSignal?.removeEventListener('abort', handleExternalAbort);
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
    if (response.status === 401 && accessToken && path !== '/auth/login') {
      unauthorizedListener?.(detail);
    }
    throw new ApiError('http', detail, response.status, data);
  }

  return data as T;
}

async function downloadBinary(path: string, fallbackFilename: string, options: RequestInit = {}): Promise<void> {
  const url = `${API_PREFIX}${path}`;
  const headers = new Headers(options.headers);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  if (accessToken) {
    headers.set('Authorization', `Bearer ${accessToken}`);
  }
  if (!(options.body instanceof FormData) && options.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method: 'GET',
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

  if (!response.ok) {
    const contentType = response.headers.get('content-type') || '';
    let payload: unknown;
    try {
      payload = contentType.includes('application/json')
        ? await response.json()
        : await response.text();
    } catch {
      payload = null;
    }
    throw new ApiError('http', extractDetail(payload), response.status, payload);
  }

  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = extractFilenameFromDisposition(response.headers.get('content-disposition'), fallbackFilename);
  anchor.style.display = 'none';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

// ========== 健康检查 API ==========

/** 获取后端健康状态 */
export async function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/health');
}

// ========== 认证 API ==========

/** 用户名密码登录 */
export async function login(payload: LoginRequest): Promise<LoginResponse> {
  return request<LoginResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/** 读取当前用户信息 */
export async function getCurrentUserProfile(): Promise<AuthProfileResponse> {
  return request<AuthProfileResponse>('/auth/me');
}

/** 读取身份目录 bootstrap */
export async function getAuthBootstrap(): Promise<IdentityBootstrapResponse> {
  return request<IdentityBootstrapResponse>('/auth/bootstrap');
}

/** 注销当前会话 */
export async function logout(): Promise<LogoutResponse> {
  return request<LogoutResponse>('/auth/logout', {
    method: 'POST',
  });
}

// ========== 日志 API ==========

/** 获取事件日志列表 */
export async function getEventLogs(query: EventLogListQuery = {}): Promise<EventLogListResponse> {
  const params = new URLSearchParams();
  if (query.page !== undefined) {
    params.set('page', String(query.page));
  }
  if (query.page_size !== undefined) {
    params.set('page_size', String(query.page_size));
  }
  if (query.category) {
    params.set('category', query.category);
  }
  if (query.action) {
    params.set('action', query.action);
  }
  if (query.outcome) {
    params.set('outcome', query.outcome);
  }
  if (query.username) {
    params.set('username', query.username);
  }
  if (query.user_id) {
    params.set('user_id', query.user_id);
  }
  if (query.department_id) {
    params.set('department_id', query.department_id);
  }
  if (query.target_id) {
    params.set('target_id', query.target_id);
  }
  if (query.rerank_strategy) {
    params.set('rerank_strategy', query.rerank_strategy);
  }
  if (query.rerank_provider) {
    params.set('rerank_provider', query.rerank_provider);
  }
  if (query.date_from) {
    params.set('date_from', query.date_from);
  }
  if (query.date_to) {
    params.set('date_to', query.date_to);
  }
  const suffix = params.toString();
  const path = suffix ? `/logs?${suffix}` : '/logs';
  return request<EventLogListResponse>(path);
}

// ========== 系统配置 API ==========

/** 读取系统配置 */
export async function getSystemConfig(): Promise<SystemConfigResponse> {
  return request<SystemConfigResponse>('/system-config');
}

/** 更新系统配置 */
export async function updateSystemConfig(payload: SystemConfigUpdateRequest): Promise<SystemConfigResponse> {
  return request<SystemConfigResponse>('/system-config', {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

// ========== 运行态汇总 API ==========

/** 读取运行态汇总 */
export async function getOpsSummary(options: { signal?: AbortSignal } = {}): Promise<OpsSummaryResponse> {
  return requestWithTimeout<OpsSummaryResponse>('/ops/summary', OPS_SUMMARY_TIMEOUT_MS, {
    signal: options.signal,
  });
}

export async function replayRequestSnapshot(
  snapshotId: string,
  payload: RequestSnapshotReplayRequest,
): Promise<RequestSnapshotReplayResponse> {
  return request<RequestSnapshotReplayResponse>(`/request-snapshots/${snapshotId}/replay`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

// ========== SOP API ==========

/** 获取 SOP 列表 */
export async function getSops(query: SopListQuery = {}): Promise<SopListResponse> {
  const params = new URLSearchParams();
  if (query.page !== undefined) {
    params.set('page', String(query.page));
  }
  if (query.page_size !== undefined) {
    params.set('page_size', String(query.page_size));
  }
  if (query.department_id) {
    params.set('department_id', query.department_id);
  }
  if (query.process_name) {
    params.set('process_name', query.process_name);
  }
  if (query.scenario_name) {
    params.set('scenario_name', query.scenario_name);
  }
  if (query.status) {
    params.set('status', query.status);
  }
  const suffix = params.toString();
  const path = suffix ? `/sops?${suffix}` : '/sops';
  return request<SopListResponse>(path);
}

/** 按场景生成 SOP 草稿 */
export async function generateSopByScenario(
  payload: SopGenerateByScenarioRequest,
): Promise<SopGenerationDraftResponse> {
  return request<SopGenerationDraftResponse>('/sops/generate/scenario', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/** 按文档直接生成 SOP 草稿 */
export async function generateSopByDocument(
  payload: SopGenerateByDocumentRequest,
): Promise<SopGenerationDraftResponse> {
  return request<SopGenerationDraftResponse>('/sops/generate/document', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/** 按主题生成 SOP 草稿 */
export async function generateSopByTopic(
  payload: SopGenerateByTopicRequest,
): Promise<SopGenerationDraftResponse> {
  return request<SopGenerationDraftResponse>('/sops/generate/topic', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

async function generateSopStream(
  path: string,
  payload: SopGenerateByDocumentRequest | SopGenerateByScenarioRequest | SopGenerateByTopicRequest,
  handlers: SopGenerationStreamHandlers = {},
  options: StreamRequestOptions = {},
): Promise<SopGenerationDraftResponse> {
  const controller = new AbortController();
  const timeout = createAbortTimeout(controller, STREAM_IDLE_TIMEOUT_MS);
  const headers = new Headers({ 'Content-Type': 'application/json' });
  const externalSignal = options.signal;
  const handleExternalAbort = () => controller.abort();

  if (externalSignal) {
    if (externalSignal.aborted) {
      controller.abort();
    } else {
      externalSignal.addEventListener('abort', handleExternalAbort, { once: true });
    }
  }

  if (accessToken && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${accessToken}`);
  }

  let response: Response;
  try {
    response = await fetch(`${API_PREFIX}${path}`, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw new ApiError('timeout', `Request timeout: ${path}`);
    }
    throw new ApiError('network', `Network error: ${path}`);
  }

  if (!response.ok) {
    let errorPayload: unknown = null;
    try {
      const contentType = response.headers.get('content-type') || '';
      errorPayload = contentType.includes('application/json') ? await response.json() : await response.text();
    } catch {
      throw new ApiError('parse', `Failed to parse stream error payload: ${path}`);
    } finally {
      timeout.clear();
    }
    if (response.status === 401 && accessToken) {
      unauthorizedListener?.(extractDetail(errorPayload));
    }
    throw new ApiError('http', extractDetail(errorPayload), response.status, errorPayload);
  }

  if (!response.body) {
    timeout.clear();
    throw new ApiError('parse', `Stream body is empty: ${path}`);
  }

  const decoder = new TextDecoder();
  const reader = response.body.getReader();
  let buffer = '';
  let finalResponse: SopGenerationDraftResponse | null = null;
  let partialContent = '';
  let latestMeta: SopGenerationStreamMeta | null = null;

  const handleFrame = (frame: string) => {
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

    let framePayload: unknown;
    try {
      framePayload = JSON.parse(dataLines.join('\n'));
    } catch {
      return;
    }

    if (eventName === 'meta') {
      latestMeta = framePayload as SopGenerationStreamMeta;
      handlers.onMeta?.(latestMeta);
      return;
    }
    if (eventName === 'content_delta') {
      const delta = (framePayload as { delta?: unknown }).delta;
      if (typeof delta === 'string' && delta) {
        partialContent += delta;
        handlers.onDelta?.(delta);
      }
      return;
    }
    if (eventName === 'done') {
      finalResponse = framePayload as SopGenerationDraftResponse;
      handlers.onDone?.(finalResponse);
      return;
    }
    if (eventName === 'error') {
      const detail = (framePayload as { message?: unknown }).message;
      throw new ApiError('http', typeof detail === 'string' ? detail : 'Unknown stream error');
    }
  };

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      timeout.touch();
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split(/\r?\n\r?\n/u);
      buffer = frames.pop() ?? '';
      for (const frame of frames) {
        handleFrame(frame);
      }
    }
    buffer += decoder.decode();
    if (buffer.trim()) {
      handleFrame(buffer);
    }
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    const message = error instanceof Error ? error.message : String(error);
    if ((error instanceof Error && error.name === 'AbortError') || controller.signal.aborted) {
      throw new ApiError('timeout', `Request timeout: ${path}`);
    }
    if (message.includes('BodyStreamBuffer was aborted')) {
      throw new ApiError('network', `Stream was aborted before the server finished sending data: ${path}`);
    }
    throw new ApiError('network', `Stream read failed: ${message}`);
  } finally {
    timeout.clear();
    externalSignal?.removeEventListener('abort', handleExternalAbort);
    try {
      reader.releaseLock();
    } catch {
      // ignore
    }
  }

  if (finalResponse) {
    return finalResponse;
  }
  const fallbackMeta = latestMeta as SopGenerationStreamMeta | null;
  if (fallbackMeta) {
    return {
      snapshot_id: null,
      request_mode: fallbackMeta.request_mode,
      generation_mode: fallbackMeta.generation_mode,
      title: fallbackMeta.title,
      department_id: fallbackMeta.department_id,
      department_name: fallbackMeta.department_name,
      process_name: fallbackMeta.process_name,
      scenario_name: fallbackMeta.scenario_name,
      topic: fallbackMeta.topic,
      content: partialContent,
      model: fallbackMeta.model,
      citations: fallbackMeta.citations,
    };
  }
  throw new ApiError('parse', `No valid stream events were received: ${path}`);
}

export async function generateSopByDocumentStream(
  payload: SopGenerateByDocumentRequest,
  handlers: SopGenerationStreamHandlers = {},
  options: StreamRequestOptions = {},
): Promise<SopGenerationDraftResponse> {
  return generateSopStream('/sops/generate/document/stream', payload, handlers, options);
}

export async function generateSopByScenarioStream(
  payload: SopGenerateByScenarioRequest,
  handlers: SopGenerationStreamHandlers = {},
  options: StreamRequestOptions = {},
): Promise<SopGenerationDraftResponse> {
  return generateSopStream('/sops/generate/scenario/stream', payload, handlers, options);
}

export async function generateSopByTopicStream(
  payload: SopGenerateByTopicRequest,
  handlers: SopGenerationStreamHandlers = {},
  options: StreamRequestOptions = {},
): Promise<SopGenerationDraftResponse> {
  return generateSopStream('/sops/generate/topic/stream', payload, handlers, options);
}

/** 保存 SOP 当前版本 */
export async function saveSop(payload: SopSaveRequest): Promise<SopSaveResponse> {
  return request<SopSaveResponse>('/sops/save', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/** 获取 SOP 详情 */
export async function getSopDetail(sopId: string): Promise<SopDetailResponse> {
  return request<SopDetailResponse>(`/sops/${encodeURIComponent(sopId)}`);
}

/** 获取 SOP 版本列表 */
export async function getSopVersions(sopId: string): Promise<SopVersionListResponse> {
  return request<SopVersionListResponse>(`/sops/${encodeURIComponent(sopId)}/versions`);
}

/** 获取 SOP 单个版本详情 */
export async function getSopVersionDetail(sopId: string, version: number): Promise<SopVersionDetailResponse> {
  return request<SopVersionDetailResponse>(`/sops/${encodeURIComponent(sopId)}/versions/${version}`);
}

/** 获取 SOP 预览 */
export async function getSopPreview(sopId: string): Promise<SopPreviewResponse> {
  return request<SopPreviewResponse>(`/sops/${encodeURIComponent(sopId)}/preview`);
}

/** 下载 SOP 文件 */
export async function downloadSopFile(sopId: string, format: 'docx' | 'pdf'): Promise<void> {
  return downloadBinary(
    `/sops/${encodeURIComponent(sopId)}/download?format=${encodeURIComponent(format)}`,
    `${sopId}.${format}`,
  );
}

/** 导出当前未保存的 SOP 草稿 */
export async function downloadSopDraftFile(payload: SopDraftExportRequest): Promise<void> {
  return downloadBinary(
    '/sops/export',
    `sop_draft.${payload.format}`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
  );
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

/** 获取文档下载地址 */
export function getDocumentDownloadUrl(docId: string): string {
  return `${API_PREFIX}/documents/${encodeURIComponent(docId)}/file`;
}

/** 删除文档（主数据状态 + 向量副本） */
export async function deleteDocument(docId: string): Promise<DocumentDeleteResponse> {
  return request<DocumentDeleteResponse>(`/documents/${encodeURIComponent(docId)}`, {
    method: 'DELETE',
  });
}

/** 删除当前用户上传的所有文档（只删自己上传的） */
export async function deleteMyDocuments(): Promise<DocumentBatchDeleteResponse> {
  return request<DocumentBatchDeleteResponse>('/documents', {
    method: 'DELETE',
  });
}

/** 重建当前用户上传的所有文档向量（用最新 chunk 配置重新入库） */
export async function rebuildMyDocuments(): Promise<DocumentBatchRebuildResponse> {
  return request<DocumentBatchRebuildResponse>('/documents/rebuild', {
    method: 'POST',
  });
}

/** 恢复当前用户已删除的文档（恢复状态并重新入库） */
export async function restoreMyDocuments(): Promise<DocumentBatchRestoreResponse> {
  return request<DocumentBatchRestoreResponse>('/documents/restore', {
    method: 'POST',
  });
}

/** 重建文档向量（异步重建任务） */
export async function rebuildDocumentVectors(docId: string): Promise<DocumentRebuildResponse> {
  return request<DocumentRebuildResponse>(`/documents/${encodeURIComponent(docId)}/rebuild`, {
    method: 'POST',
  });
}

/** 创建文档并排队入库（异步 Celery 任务） */
export async function createDocument(formData: FormData): Promise<DocumentCreateResponse> {
  return request<DocumentCreateResponse>('/documents', {
    method: 'POST',
    body: formData,  // FormData 不需要设置 Content-Type，浏览器会自动设置 boundary。
  });
}

/** 批量创建文档并排队入库（每个文件独立 job） */
export async function createDocumentsBatch(formData: FormData): Promise<DocumentBatchCreateResponse> {
  return request<DocumentBatchCreateResponse>('/documents/batch', {
    method: 'POST',
    body: formData,
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

/** 对比当前默认 rerank 路由与 heuristic 基线 */
export async function compareRetrievalRerank(req: RetrievalRequest): Promise<RetrievalRerankCompareResponse> {
  return request<RetrievalRerankCompareResponse>('/retrieval/rerank-compare', {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

export async function getRetrievalRerankCanary(limit = 8, decision?: string): Promise<RerankCanaryListResponse> {
  const params = new URLSearchParams();
  params.set('limit', String(limit));
  if (decision?.trim()) {
    params.set('decision', decision.trim());
  }
  return request<RerankCanaryListResponse>(`/retrieval/rerank-canary?${params.toString()}`);
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
export async function askQuestionStream(
  req: ChatRequest,
  handlers: ChatStreamHandlers = {},
  options: StreamRequestOptions = {},
): Promise<ChatResponse> {
  const controller = new AbortController();  // 复用统一超时逻辑，避免流式请求悬挂。
  const timeout = createAbortTimeout(controller, STREAM_IDLE_TIMEOUT_MS);
  const headers = new Headers({ 'Content-Type': 'application/json' });
  const externalSignal = options.signal;
  const handleExternalAbort = () => controller.abort();

  if (externalSignal) {
    if (externalSignal.aborted) {
      controller.abort();
    } else {
      externalSignal.addEventListener('abort', handleExternalAbort, { once: true });
    }
  }

  if (accessToken && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${accessToken}`);
  }

  let response: Response;
  try {
    response = await fetch(`${API_PREFIX}/chat/ask/stream`, {
      method: 'POST',
      headers,
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
      timeout.clear();
    }
    if (response.status === 401 && accessToken) {
      unauthorizedListener?.(extractDetail(payload));
    }
    throw new ApiError('http', extractDetail(payload), response.status, payload);
  }

  if (!response.body) {
    timeout.clear();
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
      timeout.touch();
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split(/\r?\n\r?\n/u);  // 同时兼容 LF 与 CRLF 分隔的 SSE 事件。
      buffer = frames.pop() ?? '';  // 留下最后一个不完整帧，等待下一次拼接。
      for (const frame of frames) {
        handleFrame(frame);
      }
    }
    buffer += decoder.decode();  // flush decoder，避免尾部 UTF-8 字节丢失。
    if (buffer.trim()) {  // 处理最后一个可能完整但未被分隔的帧。
      handleFrame(buffer);
    }
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    const message = error instanceof Error ? error.message : String(error);
    if ((error instanceof Error && error.name === 'AbortError') || controller.signal.aborted) {
      throw new ApiError('timeout', 'Request timeout: /chat/ask/stream');
    }
    if (message.includes('BodyStreamBuffer was aborted')) {
      throw new ApiError('network', 'Stream was aborted before the server finished sending data: /chat/ask/stream');
    }
    throw new ApiError('network', `Stream read failed: ${message}`);
  } finally {
    timeout.clear();
    externalSignal?.removeEventListener('abort', handleExternalAbort);
    try {
      reader.releaseLock();
    } catch {
      // 流已经关闭时 releaseLock 可能抛错，这里忽略避免覆盖原始异常。
    }
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
