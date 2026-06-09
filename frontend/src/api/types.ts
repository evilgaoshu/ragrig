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

export interface RerankTraceRow {
  rank: number
  chunk_id?: string
  document_uri: string
  score: number
  original_rank?: number
  rerank_score?: number
}

export interface RerankTrace {
  status?: 'applied' | 'degraded' | string
  provider?: string
  model?: string
  candidate_count?: number
  changed_count?: number
  degraded_reason?: string
  latency_ms?: number
  before?: RerankTraceRow[]
  after?: RerankTraceRow[]
}

export interface RetrievalReport {
  knowledge_base: string
  query: string
  top_k: number
  provider: string
  model: string | null
  total_results: number
  degraded?: boolean
  degraded_reason?: string
  graph_context?: GraphRetrievalContext
  cost_latency?: Record<string, unknown>
  rerank_trace?: RerankTrace
  results: RetrievalResult[]
}

export interface GraphRetrievalContext {
  matched_entities?: Record<string, unknown>[]
  matched_relationships?: Record<string, unknown>[]
  expanded_entities?: Record<string, unknown>[]
  relation_paths?: Record<string, unknown>[]
  chunk_scores?: Record<string, number>
  rank_movement?: Record<string, unknown>[]
  diagnostics?: Record<string, unknown>
  degraded?: boolean
  degraded_reason?: string
}

export interface KnowledgeGraphStats {
  entity_count: number
  mention_count: number
  relation_count: number
  relation_evidence_count: number
  claim_count: number
  source_chunk_count: number
  document_count: number
  graph_evidence_chunk_count: number
}

export interface KnowledgeGraphMention {
  id: string
  chunk_id: string
  document_id: string
  document_version_id: string
  mention_text: string
  char_start: number | null
  char_end: number | null
  confidence: number
  text_preview: string
  document_uri: string
}

export interface KnowledgeGraphEntity {
  id: string
  canonical_name: string
  display_name: string
  entity_type: string
  description: string | null
  confidence: number
  extractor_version: string
  mention_count: number
  evidence_chunks: KnowledgeGraphMention[]
  metadata: Record<string, unknown>
}

export interface KnowledgeGraphRelationEvidence {
  id: string
  chunk_id: string
  document_id: string
  document_version_id: string
  evidence_text: string
  text_preview: string
  document_uri: string
  confidence: number
}

export interface RelationFeedbackSummary {
  correct?: number
  incorrect?: number
  needs_review?: number
  total?: number
}

export interface KnowledgeGraphRelation {
  id: string
  subject_entity_id: string
  subject: string
  predicate: string
  object_entity_id: string
  object: string
  confidence: number
  extractor_version: string
  evidence: KnowledgeGraphRelationEvidence[]
  metadata: Record<string, unknown> & { feedback_summary?: RelationFeedbackSummary }
}

export interface KnowledgeGraphClaim {
  id: string
  claim_text: string
  confidence: number
  source_chunk_id: string
  document_id: string
  document_version_id: string
  document_uri: string
  text_preview: string
  extractor_version: string
  metadata: Record<string, unknown>
}

export interface KnowledgeGraphResult {
  schema_version: string
  status: string
  knowledge_base_id: string
  knowledge_base: string
  generated_from: string
  stats: KnowledgeGraphStats
  entities: KnowledgeGraphEntity[]
  relations: KnowledgeGraphRelation[]
  claims: KnowledgeGraphClaim[]
  limitations: string[]
  trace: Record<string, unknown>
}

export interface RetrievalPreferences {
  mode: string
  lexical_weight: number
  vector_weight: number
  candidate_k: number
  reranker_provider: string | null
  reranker_model: string | null
  graph_weight: number
  graph_depth: number
}

export interface RetrievalPreferenceResponse {
  status?: string
  knowledge_base_id: string
  knowledge_base: string
  preferences: RetrievalPreferences
}

export interface RelationFeedbackResponse {
  status: string
  relation_id: string
  feedback: Record<string, unknown>
  feedback_summary: RelationFeedbackSummary
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
