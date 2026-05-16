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

export interface PipelineRun {
  id: string
  knowledge_base: string
  status: string
  item_count: number
  created_at: string
  updated_at: string
  error: string | null
}

export interface Source {
  id: string
  plugin_id: string
  label: string
  config: Record<string, unknown>
  knowledge_base: string | null
  created_at: string
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

export interface EmbeddingProfile {
  provider: string
  model: string
  dimensions: number | null
  chunk_count: number
}

export interface TaskRecord {
  id: string
  task_type: string
  status: string
  error: string | null
  created_at: string
  updated_at: string
}
