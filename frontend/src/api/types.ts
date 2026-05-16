export interface KnowledgeBase {
  id: string
  name: string
  workspace_id: string
  document_count: number
  chunk_count: number
  embedding_model: string | null
  created_at: string
}

export interface SystemStatus {
  api: string
  api_version: string
  database: string
  database_detail: string | null
  vector: string
  vector_detail: string | null
  knowledge_bases: number
  recent_pipeline_runs: number
  embedding_profiles: number
}

export interface Source {
  id: string
  knowledge_base: string
  kind: string
  uri: string
  config: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface PipelineRun {
  id: string
  run_type: string
  knowledge_base: string
  source_uri: string | null
  status: string
  total_items: number
  success_count: number
  skipped_count: number
  failure_count: number
  error_message: string | null
  started_at: string
  finished_at: string | null
  dag: unknown
}

export interface PipelineRunItem {
  id: string
  document_uri: string
  status: string
  error: string | null
  started_at: string
  finished_at: string | null
}

export interface RetrievalResult {
  chunk_id: string
  document_id: string
  document_version_id: string
  document_uri: string
  source_uri: string | null
  text: string
  text_preview: string
  distance: number
  score: number
  chunk_metadata: Record<string, unknown>
  rank_stage_trace: unknown
}

export interface RetrievalReport {
  knowledge_base: string
  query: string
  top_k: number
  provider: string
  model: string
  total_results: number
  results: RetrievalResult[]
}

export interface TaskRecord {
  task_id: string
  status: string
  result: unknown
  error: string | null
  progress: unknown
}

export interface UploadResult {
  task_id: string
  pipeline_run_id: string
  accepted_files: number
  rejected_files: number
  rejections: { filename: string; reason: string; detail?: string }[]
  warnings: string[]
}

export interface DocumentVersionSummary {
  id: string
  version_number: number
  parser_name: string
  parser_config: Record<string, unknown>
  metadata: Record<string, unknown>
  text_preview: string
  chunk_count: number
  created_at: string
}

export interface Document {
  id: string
  knowledge_base: string
  uri: string
  source_uri: string
  mime_type: string
  content_hash: string
  metadata: Record<string, unknown>
  acl_summary: Record<string, unknown>
  latest_version: DocumentVersionSummary
}

export interface Chunk {
  id: string
  chunk_index: number
  heading: string | null
  char_start: number
  char_end: number
  page_number: number | null
  text: string
  metadata: Record<string, unknown>
}

export interface SupportedFormat {
  extension: string
  mime_type: string
  display_name: string
  parser_id: string
  status: 'supported' | 'preview' | 'planned'
  fallback_policy: string | null
  max_file_size_mb: number
  capabilities: string[]
  limitations: string | null
  docs_reference: string | null
}
