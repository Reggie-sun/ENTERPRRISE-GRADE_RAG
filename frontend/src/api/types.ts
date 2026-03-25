/**
 * API 类型定义文件
 * 与后端 Pydantic Schema 保持一致
 */

// ========== 通用类型 ==========

/** ACL 可见性枚举 */
export type Visibility = 'public' | 'department' | 'role' | 'private';

/** 文档密级枚举 */
export type Classification = 'public' | 'internal' | 'confidential' | 'secret';

/** 文档生命周期状态 */
export type DocumentLifecycleStatus = 'queued' | 'uploaded' | 'active' | 'failed' | 'partial_failed';

/** Ingest Job 状态枚举 */
export type IngestJobStatus =
  | 'pending'
  | 'uploaded'
  | 'queued'
  | 'parsing'
  | 'ocr_processing'
  | 'chunking'
  | 'embedding'
  | 'indexing'
  | 'completed'
  | 'failed'
  | 'dead_letter'
  | 'partial_failed';

/** Ingest Job 错误码枚举 */
export type IngestErrorCode =
  | 'INGEST_DISPATCH_ERROR'
  | 'INGEST_DISPATCH_ERROR_DEAD_LETTER'
  | 'INGEST_VALIDATION_ERROR'
  | 'INGEST_VALIDATION_ERROR_DEAD_LETTER'
  | 'INGEST_RUNTIME_ERROR'
  | 'INGEST_RUNTIME_ERROR_DEAD_LETTER';

// ========== 健康检查 ==========

/** 健康检查响应 */
export interface HealthResponse {
  status: string;  // 服务状态。
  app_name: string;  // 应用名称。
  environment: string;  // 运行环境。
  vector_store: {
    provider: string;  // 向量库提供方。
    url: string;  // 向量库地址。
    collection: string;  // Collection 名称。
  };
  llm: {
    provider: string;  // LLM 提供方。
    base_url: string;  // LLM 服务地址。
    model: string;  // LLM 模型名称。
  };
  embedding: {
    provider: string;  // Embedding 提供方。
    base_url: string;  // Embedding 服务地址。
    model: string;  // Embedding 模型名称。
  };
  queue: {
    provider: string;  // 队列提供方。
    broker_url: string;  // broker 地址。
    result_backend: string;  // 结果后端地址。
    ingest_queue: string;  // 入库队列名。
  };
  metadata_store: {
    provider: string;  // 元数据存储类型。
    postgres_enabled: boolean;  // 是否启用 PostgreSQL 元数据真源。
    dsn_configured: boolean;  // 是否配置了 DSN。
  };
}

// ========== 文档相关 ==========

/** POST /documents 响应 - 创建文档并排队入库 */
export interface DocumentCreateResponse {
  doc_id: string;  // 新创建文档的唯一标识。
  job_id: string;  // 本次入库任务的唯一标识。
  status: 'queued';  // 当前创建结果固定为 queued。
}

/** POST /documents/upload 响应 - 同步上传并入库 */
export interface DocumentUploadResponse {
  document_id: string;  // 上传文档的唯一标识。
  filename: string;  // 原始文件名。
  content_type: string | null;  // 文件 MIME 类型。
  size_bytes: number;  // 文件大小（字节）。
  status: 'ingested';  // 当前上传状态。
  parse_supported: boolean;  // 是否支持解析。
  storage_path: string;  // 原始文件落盘路径。
  parsed_path: string;  // 解析后文本文件路径。
  chunk_path: string;  // chunk 结果 JSON 文件路径。
  collection_name: string;  // 向量写入的 Qdrant collection 名称。
  parser_name: string;  // 使用的解析器名称。
  chunk_count: number;  // 生成的 chunk 数量。
  vector_count: number;  // 写入的向量数量。
  created_at: string;  // 上传完成时间。
}

/** 文档摘要 - 列表项 */
export interface DocumentSummary {
  document_id: string;  // 文档唯一标识。
  filename: string;  // 文档文件名。
  size_bytes: number;  // 文件大小。
  parse_supported: boolean;  // 是否支持解析。
  storage_path: string;  // 文件落盘路径。
  status: DocumentLifecycleStatus;  // 文档主状态。
  ingest_status: IngestJobStatus | null;  // 最近一次 ingest 任务状态。
  latest_job_id: string | null;  // 最近一次 ingest 任务 ID。
  department_id: string | null;  // 文档主部门。
  category_id: string | null;  // 文档二级分类。
  uploaded_by: string | null;  // 上传人。
  updated_at: string;  // 最近更新时间。
}

/** 文档列表查询参数 */
export interface DocumentListQuery {
  page?: number;  // 页码（从 1 开始）。
  page_size?: number;  // 每页数量。
  keyword?: string;  // 文件名或文档 ID 关键字。
  department_id?: string;  // 主部门筛选。
  category_id?: string;  // 分类筛选。
  status?: DocumentLifecycleStatus;  // 文档状态筛选。
}

/** GET /documents 响应 - 文档列表 */
export interface DocumentListResponse {
  total: number;  // 文档总数。
  page: number;  // 当前页码。
  page_size: number;  // 当前每页数量。
  items: DocumentSummary[];  // 文档摘要列表。
}

/** 文档详情 */
export interface DocumentDetailResponse {
  doc_id: string;  // 文档唯一标识。
  file_name: string;  // 原始文件名。
  status: DocumentLifecycleStatus;  // 当前文档状态。
  ingest_status: IngestJobStatus | null;  // 最近一次 ingest 状态。
  department_id: string | null;  // 文档主部门。
  category_id: string | null;  // 文档二级分类。
  uploaded_by: string | null;  // 上传人。
  current_version: number;  // 当前版本。
  latest_job_id: string;  // 最近一次入库任务 ID。
  created_at: string;  // 创建时间。
  updated_at: string;  // 更新时间。
}

/** 文档预览响应 */
export interface DocumentPreviewResponse {
  doc_id: string;  // 文档唯一标识。
  file_name: string;  // 原始文件名。
  preview_type: 'text' | 'pdf';  // 预览类型。
  content_type: string;  // 预览内容类型。
  text_content: string | null;  // 文本预览内容，PDF 场景可为空。
  text_truncated: boolean;  // 文本是否被截断。
  preview_file_url: string | null;  // 在线预览文件流地址（如 PDF）。
  updated_at: string;  // 文档更新时间。
}

// ========== Ingest Job 相关 ==========

/** GET /ingest/jobs/{job_id} 响应 - 任务状态 */
export interface IngestJobStatusResponse {
  job_id: string;  // 任务唯一标识。
  doc_id: string;  // 关联文档 ID。
  status: IngestJobStatus;  // 当前状态。
  progress: number;  // 当前进度百分比（0-100）。
  stage: string;  // 当前阶段名。
  retry_count: number;  // 重试次数。
  max_retry_limit: number;  // 最大重试次数限制。
  auto_retry_eligible: boolean;  // 是否处于自动重试窗口内。
  manual_retry_allowed: boolean;  // 是否允许手动重投递。
  error_code: IngestErrorCode | null;  // 错误码。
  error_message: string | null;  // 错误描述。
  created_at: string;  // 创建时间。
  updated_at: string;  // 更新时间。
}

// ========== 检索相关 ==========

/** 检索请求 */
export interface RetrievalRequest {
  query: string;  // 用户输入的检索问题。
  top_k: number;  // 要返回的检索结果数量。
  document_id?: string;  // 可选文档过滤条件，只检索指定文档。
}

/** 单条检索结果 */
export interface RetrievedChunk {
  chunk_id: string;  // chunk 唯一标识。
  document_id: string;  // chunk 所属文档唯一标识。
  document_name: string;  // chunk 所属文档名称。
  text: string;  // chunk 文本内容。
  score: number;  // chunk 匹配分数。
  source_path: string;  // 原始文档路径。
}

/** 检索响应 */
export interface RetrievalResponse {
  query: string;  // 原始查询文本。
  top_k: number;  // 本次请求的 top_k 值。
  mode: string;  // 当前检索模式。
  results: RetrievedChunk[];  // 返回的检索结果列表。
}

// ========== 问答相关 ==========

/** 问答请求 */
export interface ChatRequest {
  question: string;  // 用户输入的问题文本。
  top_k: number;  // 检索阶段返回的候选片段数量。
  document_id?: string;  // 可选文档过滤条件，只在指定文档范围内召回引用。
}

/** 引用片段 */
export interface Citation {
  chunk_id: string;  // 当前引用片段的 chunk 唯一标识。
  document_id: string;  // 当前片段所属文档的唯一标识。
  document_name: string;  // 当前片段所属文档名。
  snippet: string;  // 当前引用片段的文本内容。
  score: number;  // 当前片段的匹配分数。
  source_path: string;  // 当前片段原始文件的路径。
}

/** 问答响应 */
export interface ChatResponse {
  question: string;  // 原始用户问题。
  answer: string;  // 生成出的回答内容。
  mode: string;  // 当前回答模式。
  model: string;  // 当前使用的生成模型名称。
  citations: Citation[];  // 回答中附带的引用片段列表。
}
