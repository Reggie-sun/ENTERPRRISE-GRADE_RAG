/**
 * API 类型定义文件
 * 与后端 Pydantic Schema 保持一致
 */

// ========== 通用类型 ==========

/** ACL 可见性枚举 */
export type Visibility = 'public' | 'department' | 'role' | 'private';

/** 文档密级枚举 */
export type Classification = 'public' | 'internal' | 'confidential' | 'secret';

/** 最小角色集合 */
export type UserRole = 'employee' | 'department_admin' | 'sys_admin';
export type SopStatus = 'draft' | 'active' | 'archived';
export type SopDownloadFormat = 'docx' | 'pdf';
export type QueryMode = 'fast' | 'accurate';
export type EventLogCategory = 'chat' | 'document' | 'sop_generation';
export type EventLogOutcome = 'success' | 'failed';
export type RequestTraceStageName = 'query_rewrite' | 'retrieval' | 'rerank' | 'llm' | 'answer';
export type RequestTraceStageStatus = 'success' | 'failed' | 'skipped' | 'degraded';
export type RequestSnapshotReplayMode = 'original' | 'current';

/** 文档生命周期状态 */
export type DocumentLifecycleStatus = 'queued' | 'uploaded' | 'active' | 'failed' | 'partial_failed' | 'deleted';

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
  ocr: {
    provider: string;  // OCR provider 类型。
    language: string;  // OCR 默认语言。
    enabled: boolean;  // 是否启用 OCR。
    ready: boolean;  // 当前 provider 是否已具备运行依赖。
    pdf_native_text_min_chars: number;  // PDF 原生文本低于该阈值时尝试 OCR fallback。
    angle_cls_enabled: boolean;  // PaddleOCR 是否启用 angle cls。
    detail: string | null;  // OCR 运行状态说明。
  };
}

// ========== 认证相关 ==========

/** 角色定义 */
export interface RoleDefinition {
  role_id: UserRole;
  name: string;
  description: string;
  data_scope: 'department' | 'global';
  is_admin: boolean;
}

/** 部门记录 */
export interface DepartmentRecord {
  department_id: string;
  tenant_id: string;
  department_name: string;
  parent_department_id: string | null;
  is_active: boolean;
}

/** 用户记录 */
export interface UserRecord {
  user_id: string;
  tenant_id: string;
  username: string;
  display_name: string;
  department_id: string;
  role_id: UserRole;
  is_active: boolean;
}

/** 当前用户权限上下文 */
export interface AuthProfileResponse {
  user: UserRecord;
  role: RoleDefinition;
  department: DepartmentRecord;
  accessible_department_ids: string[];
}

/** 登录请求 */
export interface LoginRequest {
  username: string;
  password: string;
}

/** 登录响应 */
export interface LoginResponse extends AuthProfileResponse {
  access_token: string;
  token_type: 'bearer';
  expires_in_seconds: number;
}

/** 登出响应 */
export interface LogoutResponse {
  status: 'logged_out';
}

/** 身份目录 bootstrap */
export interface IdentityBootstrapResponse {
  roles: RoleDefinition[];
  departments: DepartmentRecord[];
  users: UserRecord[];
}

// ========== 日志相关 ==========

export interface EventLogActor {
  tenant_id: string | null;
  user_id: string | null;
  username: string | null;
  role_id: UserRole | null;
  department_id: string | null;
}

export interface EventLogRecord {
  event_id: string;
  category: EventLogCategory;
  action: string;
  outcome: EventLogOutcome;
  occurred_at: string;
  actor: EventLogActor;
  target_type: string | null;
  target_id: string | null;
  mode: string | null;
  top_k: number | null;
  candidate_top_k: number | null;
  rerank_top_n: number | null;
  duration_ms: number | null;
  timeout_flag: boolean;
  downgraded_from: string | null;
  details: Record<string, unknown>;
}

export interface EventLogListQuery {
  page?: number;
  page_size?: number;
  category?: EventLogCategory;
  action?: string;
  outcome?: EventLogOutcome;
  username?: string;
  user_id?: string;
  department_id?: string;
  target_id?: string;
  date_from?: string;
  date_to?: string;
}

export interface EventLogListResponse {
  items: EventLogRecord[];
  total: number;
  page: number;
  page_size: number;
}

// ========== Trace 相关 ==========

export interface RequestTraceStage {
  stage: RequestTraceStageName;
  status: RequestTraceStageStatus;
  duration_ms: number | null;
  input_size: number | null;
  output_size: number | null;
  cache_hit: boolean | null;
  details: Record<string, unknown>;
}

export interface RequestTraceRecord {
  trace_id: string;
  request_id: string;
  category: EventLogCategory;
  action: string;
  outcome: EventLogOutcome;
  occurred_at: string;
  actor: EventLogActor;
  target_type: string | null;
  target_id: string | null;
  mode: string | null;
  top_k: number | null;
  candidate_top_k: number | null;
  rerank_top_n: number | null;
  total_duration_ms: number | null;
  timeout_flag: boolean;
  downgraded_from: string | null;
  response_mode: string | null;
  error_message: string | null;
  stages: RequestTraceStage[];
  details: Record<string, unknown>;
}

export interface RequestTraceListResponse {
  items: RequestTraceRecord[];
  total: number;
  page: number;
  page_size: number;
}

// ========== Request Snapshot 相关 ==========

export interface RequestSnapshotRewrite {
  status: 'skipped' | 'applied' | 'failed';
  original_question: string;
  rewritten_question: string | null;
  details: Record<string, unknown>;
}

export interface RequestSnapshotContext {
  rank: number;
  chunk_id: string;
  document_id: string;
  document_name: string;
  snippet: string;
  score: number;
  source_path: string;
}

export interface RequestSnapshotModelRoute {
  provider: string;
  base_url: string | null;
  model: string;
}

export interface RequestSnapshotComponentVersions {
  prompt_version: string;
  embedding_provider: string;
  embedding_model: string;
  reranker_provider: string;
  reranker_model: string;
}

export interface RequestSnapshotResult {
  response_mode: string;
  model: string;
  answer_preview: string | null;
  answer_chars: number;
  citation_count: number;
  rerank_strategy: string;
  downgraded_from: string | null;
  timeout_flag: boolean;
  error_message: string | null;
}

export interface RequestSnapshotRecord {
  snapshot_id: string;
  trace_id: string;
  request_id: string;
  category: EventLogCategory;
  action: string;
  outcome: EventLogOutcome;
  occurred_at: string;
  actor: EventLogActor;
  target_type: string | null;
  target_id: string | null;
  request: ChatRequest | SopGenerateByDocumentRequest | SopGenerateByScenarioRequest | SopGenerateByTopicRequest;
  profile: {
    purpose: 'retrieval' | 'chat' | 'sop_generation';
    mode: QueryMode;
    top_k: number;
    candidate_top_k: number;
    rerank_top_n: number;
    timeout_budget_seconds: number;
    fallback_mode: QueryMode | null;
  };
  memory_summary: string | null;
  rewrite: RequestSnapshotRewrite;
  contexts: RequestSnapshotContext[];
  citations: ChatResponse['citations'];
  model_route: RequestSnapshotModelRoute;
  component_versions: RequestSnapshotComponentVersions;
  result: RequestSnapshotResult;
  details: Record<string, unknown>;
}

export interface RequestSnapshotReplayRequest {
  replay_mode: RequestSnapshotReplayMode;
}

export interface RequestSnapshotReplayResponse {
  snapshot_id: string;
  replay_mode: RequestSnapshotReplayMode;
  original_trace_id: string;
  original_request_id: string;
  replayed_request: ChatRequest | SopGenerateByDocumentRequest | SopGenerateByScenarioRequest | SopGenerateByTopicRequest;
  response: ChatResponse | SopGenerationDraftResponse;
}

// ========== 系统配置相关 ==========

export interface QueryModeConfig {
  top_k_default: number;
  candidate_multiplier: number;
  rerank_top_n: number;
  timeout_budget_seconds: number;
}

export interface QueryProfilesConfig {
  fast: QueryModeConfig;
  accurate: QueryModeConfig;
}

export interface ModelRoutingConfig {
  fast_model: string;
  accurate_model: string;
  sop_generation_model: string;
}

export interface DegradeControlsConfig {
  rerank_fallback_enabled: boolean;
  accurate_to_fast_fallback_enabled: boolean;
  retrieval_fallback_enabled: boolean;
}

export interface RetryControlsConfig {
  llm_retry_enabled: boolean;
  llm_retry_max_attempts: number;
  llm_retry_backoff_ms: number;
}

export interface ConcurrencyControlsConfig {
  fast_max_inflight: number;
  accurate_max_inflight: number;
  sop_generation_max_inflight: number;
  per_user_online_max_inflight: number;
  acquire_timeout_ms: number;
  busy_retry_after_seconds: number;
}

export interface SystemConfigResponse {
  query_profiles: QueryProfilesConfig;
  model_routing: ModelRoutingConfig;
  degrade_controls: DegradeControlsConfig;
  retry_controls: RetryControlsConfig;
  concurrency_controls: ConcurrencyControlsConfig;
  updated_at: string | null;
  updated_by: string | null;
}

export interface SystemConfigUpdateRequest {
  query_profiles: QueryProfilesConfig;
  model_routing: ModelRoutingConfig;
  degrade_controls: DegradeControlsConfig;
  retry_controls: RetryControlsConfig;
  concurrency_controls: ConcurrencyControlsConfig;
}

// ========== 运行态汇总相关 ==========

export interface OpsQueueSummary {
  available: boolean;
  ingest_queue: string;
  backlog: number | null;
  error: string | null;
}

export interface OpsRecentWindowSummary {
  sample_size: number;
  failed_count: number;
  timeout_count: number;
  downgraded_count: number;
  duration_count: number;
  duration_p50_ms: number | null;
  duration_p95_ms: number | null;
  duration_p99_ms: number | null;
}

export interface OpsCategorySummary {
  category: EventLogCategory;
  total: number;
  failed_count: number;
  timeout_count: number;
  downgraded_count: number;
  last_event_at: string | null;
  last_failed_at: string | null;
}

export interface OpsRuntimeChannelSummary {
  channel: 'chat_fast' | 'chat_accurate' | 'sop_generation';
  inflight: number;
  limit: number;
  available_slots: number;
}

export interface OpsRuntimeGateSummary {
  acquire_timeout_ms: number;
  busy_retry_after_seconds: number;
  per_user_online_max_inflight: number;
  active_users: number;
  max_user_inflight: number;
  channels: OpsRuntimeChannelSummary[];
}

export interface OpsSummaryResponse {
  checked_at: string;
  health: HealthResponse;
  queue: OpsQueueSummary;
  runtime_gate: OpsRuntimeGateSummary;
  recent_window: OpsRecentWindowSummary;
  categories: OpsCategorySummary[];
  recent_failures: EventLogRecord[];
  recent_degraded: EventLogRecord[];
  recent_traces: RequestTraceRecord[];
  recent_snapshots: RequestSnapshotRecord[];
  config: SystemConfigResponse;
}

// ========== SOP 相关 ==========

export type SopGenerationRequestMode = 'scenario' | 'topic' | 'document';

export interface SopGenerationCitation {
  chunk_id: string;
  document_id: string;
  document_name: string;
  snippet: string;
  score: number;
  source_path: string;
}

export interface SopGenerateByScenarioRequest {
  scenario_name: string;
  process_name?: string;
  mode?: QueryMode;
  top_k?: number;
  department_id?: string;
  document_id?: string;
  title_hint?: string;
}

export interface SopGenerateByTopicRequest {
  topic: string;
  process_name?: string;
  scenario_name?: string;
  mode?: QueryMode;
  top_k?: number;
  department_id?: string;
  document_id?: string;
  title_hint?: string;
}

export interface SopGenerateByDocumentRequest {
  document_id: string;
  process_name?: string;
  scenario_name?: string;
  mode?: QueryMode;
  top_k?: number;
  department_id?: string;
  title_hint?: string;
}

export interface SopDraftExportRequest {
  title: string;
  content: string;
  format: SopDownloadFormat;
  department_id?: string;
  process_name?: string;
  scenario_name?: string;
  source_document_id?: string;
}

export interface SopGenerationDraftResponse {
  snapshot_id: string | null;
  request_mode: SopGenerationRequestMode;
  generation_mode: string;
  title: string;
  department_id: string;
  department_name: string;
  process_name: string | null;
  scenario_name: string | null;
  topic: string | null;
  content: string;
  model: string;
  citations: SopGenerationCitation[];
}

/** SOP 摘要 - 列表项 */
export interface SopSummary {
  sop_id: string;
  title: string;
  department_id: string;
  department_name: string;
  process_name: string | null;
  scenario_name: string | null;
  version: number;
  status: SopStatus;
  preview_available: boolean;
  downloadable_formats: SopDownloadFormat[];
  updated_at: string;
}

/** SOP 列表查询参数 */
export interface SopListQuery {
  page?: number;
  page_size?: number;
  department_id?: string;
  process_name?: string;
  scenario_name?: string;
  status?: SopStatus;
}

/** GET /sops 响应 */
export interface SopListResponse {
  total: number;
  page: number;
  page_size: number;
  items: SopSummary[];
}

/** SOP 详情 */
export interface SopDetailResponse {
  sop_id: string;
  title: string;
  tenant_id: string;
  department_id: string;
  department_name: string;
  process_name: string | null;
  scenario_name: string | null;
  version: number;
  status: SopStatus;
  preview_resource_path: string | null;
  preview_resource_type: 'text' | 'html' | 'pdf';
  download_docx_available: boolean;
  download_pdf_available: boolean;
  tags: string[];
  source_document_id: string | null;
  created_by: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
}

/** SOP 预览响应 */
export interface SopPreviewResponse {
  sop_id: string;
  title: string;
  preview_type: 'text' | 'html' | 'pdf';
  content_type: string;
  text_content: string | null;
  preview_file_url: string | null;
  updated_at: string;
}

export interface SopSaveRequest {
  sop_id?: string;
  title: string;
  department_id?: string;
  process_name?: string;
  scenario_name?: string;
  topic?: string;
  status: SopStatus;
  content: string;
  request_mode?: SopGenerationRequestMode;
  generation_mode: string;
  citations: SopGenerationCitation[];
  tags?: string[];
}

export interface SopSaveResponse {
  sop_id: string;
  version: number;
  status: SopStatus;
  title: string;
  saved_at: string;
}

export interface SopVersionSummary {
  sop_id: string;
  version: number;
  title: string;
  status: SopStatus;
  generation_mode: string;
  request_mode: SopGenerationRequestMode | null;
  citations_count: number;
  created_by: string | null;
  updated_by: string | null;
  updated_at: string;
  is_current: boolean;
}

export interface SopVersionListResponse {
  sop_id: string;
  current_version: number;
  items: SopVersionSummary[];
}

export interface SopVersionDetailResponse {
  sop_id: string;
  version: number;
  title: string;
  tenant_id: string;
  department_id: string;
  process_name: string | null;
  scenario_name: string | null;
  topic: string | null;
  status: SopStatus;
  content: string;
  request_mode: SopGenerationRequestMode | null;
  generation_mode: string;
  citations: SopGenerationCitation[];
  tags: string[];
  created_by: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
  is_current: boolean;
}

// ========== 文档相关 ==========

/** POST /documents 响应 - 创建文档并排队入库 */
export interface DocumentCreateResponse {
  doc_id: string;  // 新创建文档的唯一标识。
  job_id: string;  // 本次入库任务的唯一标识。
  status: 'queued';  // 当前创建结果固定为 queued。
}

/** POST /documents/batch 单文件结果 */
export interface DocumentBatchItemResponse {
  file_name: string;  // 当前文件名。
  status: 'queued' | 'failed';  // 当前文件处理结果。
  doc_id: string | null;  // 成功创建时返回 doc_id。
  job_id: string | null;  // 成功创建时返回 job_id。
  http_status: number | null;  // 失败时返回对应 HTTP 状态码。
  error_code: string | null;  // 失败时返回可选错误码。
  error_message: string | null;  // 失败时返回错误文本。
}

/** POST /documents/batch 响应 - 批量创建文档并排队入库 */
export interface DocumentBatchCreateResponse {
  total: number;  // 本次批量上传总文件数。
  queued: number;  // 成功入队文件数。
  failed: number;  // 失败文件数。
  items: DocumentBatchItemResponse[];  // 各文件处理结果。
}

/** POST /documents/upload 响应 - 同步上传并入库 */
export interface DocumentUploadResponse {
  document_id: string;  // 上传文档的唯一标识。
  filename: string;  // 原始文件名。
  content_type: string | null;  // 文件 MIME 类型。
  size_bytes: number;  // 文件大小（字节）。
  status: 'ingested' | 'partial_failed';  // 当前上传状态。
  parse_supported: boolean;  // 是否支持解析。
  storage_path: string;  // 原始文件落盘路径。
  parsed_path: string;  // 解析后文本文件路径。
  chunk_path: string;  // chunk 结果 JSON 文件路径。
  ocr_artifact_path: string | null;  // OCR 中间产物路径；非 OCR 文档为空。
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

/** 文档删除响应 */
export interface DocumentDeleteResponse {
  doc_id: string;  // 被删除的文档 ID。
  status: 'deleted';  // 删除动作状态。
  vector_points_removed: number;  // 清理掉的向量点位数量。
}

/** 文档重建向量响应 */
export interface DocumentRebuildResponse {
  doc_id: string;  // 触发重建的文档 ID。
  job_id: string;  // 新生成的重建任务 ID。
  status: 'queued';  // 当前重建任务状态。
  previous_vector_points_removed: number;  // 重建前清理掉的旧向量点位数量。
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
  top_k?: number;  // 要返回的检索结果数量。
  mode?: QueryMode;  // 可选查询档位。
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
  top_k?: number;  // 检索阶段返回的候选片段数量。
  mode?: QueryMode;  // 可选查询档位。
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
