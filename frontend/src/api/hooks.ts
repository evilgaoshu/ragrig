import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type {
  KnowledgeBase,
  SystemStatus,
  Source,
  PipelineRun,
  PipelineRunItem,
  RetrievalReport,
  TaskRecord,
  UploadResult,
  SupportedFormat,
  Document,
  Chunk,
} from './types'

export function useSystemStatus() {
  return useQuery({
    queryKey: ['system-status'],
    queryFn: () => api.get<SystemStatus>('/system/status'),
    refetchInterval: 30_000,
  })
}

export function useKnowledgeBases() {
  return useQuery({
    queryKey: ['knowledge-bases'],
    queryFn: () => api.get<{ items: KnowledgeBase[] }>('/knowledge-bases').then((r) => r.items),
  })
}

export function useCreateKnowledgeBase() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => api.post('/knowledge-bases', { name }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['knowledge-bases'] }),
  })
}

export function useSources() {
  return useQuery({
    queryKey: ['sources'],
    queryFn: () => api.get<{ items: Source[] }>('/sources').then((r) => r.items),
  })
}

export function usePipelineRuns() {
  return useQuery({
    queryKey: ['pipeline-runs'],
    queryFn: () => api.get<{ items: PipelineRun[] }>('/pipeline-runs').then((r) => r.items),
    refetchInterval: 10_000,
  })
}

export function usePipelineRunDetail(runId: string | null) {
  return useQuery({
    queryKey: ['pipeline-run', runId],
    queryFn: () => api.get<PipelineRun>(`/pipeline-runs/${runId}`),
    enabled: !!runId,
  })
}

export function usePipelineRunItems(runId: string | null) {
  return useQuery({
    queryKey: ['pipeline-run-items', runId],
    queryFn: () =>
      api.get<{ items: PipelineRunItem[] }>(`/pipeline-runs/${runId}/items`).then((r) => r.items),
    enabled: !!runId,
    refetchInterval: 5_000,
  })
}

export function useTask(taskId: string | null) {
  return useQuery({
    queryKey: ['task', taskId],
    queryFn: () => api.get<TaskRecord>(`/tasks/${taskId}`),
    enabled: !!taskId,
    refetchInterval: (q) => {
      const status = (q.state.data as TaskRecord | undefined)?.status
      return status === 'queued' || status === 'running' ? 2_000 : false
    },
  })
}

export function useRetrieval() {
  return useMutation({
    mutationFn: (body: {
      knowledge_base: string
      query: string
      top_k: number
      provider: string
      model: string | null
      mode: string
    }) => api.post<RetrievalReport>('/retrieval/search', body),
  })
}

export function useSupportedFormats() {
  return useQuery({
    queryKey: ['supported-formats'],
    queryFn: () =>
      api.get<{ formats: SupportedFormat[] }>('/supported-formats').then((r) => r.formats),
  })
}

export function useUpload() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ kbName, files }: { kbName: string; files: File[] }) => {
      const form = new FormData()
      files.forEach((f) => form.append('files', f))
      return api.postForm<UploadResult>(`/knowledge-bases/${encodeURIComponent(kbName)}/upload`, form)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pipeline-runs'] })
      qc.invalidateQueries({ queryKey: ['knowledge-bases'] })
    },
  })
}

export function useDocuments() {
  return useQuery({
    queryKey: ['documents'],
    queryFn: () => api.get<{ items: Document[] }>('/documents').then((r) => r.items),
  })
}

export function useDocumentVersionChunks(versionId: string | null) {
  return useQuery({
    queryKey: ['document-version-chunks', versionId],
    queryFn: () =>
      api
        .get<{ items: Chunk[] }>(`/document-versions/${versionId}/chunks`)
        .then((r) => r.items),
    enabled: !!versionId,
  })
}

export function useSanitizerCoverage() {
  return useQuery({
    queryKey: ['sanitizer-coverage'],
    queryFn: () => api.get<Record<string, unknown> | null>('/sanitizer-coverage'),
  })
}

export function useSanitizerDriftSummary() {
  return useQuery({
    queryKey: ['sanitizer-drift-summary'],
    queryFn: () => api.get<Record<string, unknown>>('/sanitizer-drift-history-summary'),
  })
}

export function useSanitizerDriftHistory() {
  return useQuery({
    queryKey: ['sanitizer-drift-history'],
    queryFn: () => api.get<Record<string, unknown>>('/sanitizer-drift-history'),
  })
}

export function useRetrievalBenchmarkRecent() {
  return useQuery({
    queryKey: ['retrieval-benchmark-recent'],
    queryFn: () => api.get<Record<string, unknown>>('/retrieval/benchmark/recent'),
  })
}

export function useRetrievalBenchmarkIntegrity() {
  return useQuery({
    queryKey: ['retrieval-benchmark-integrity'],
    queryFn: () => api.get<Record<string, unknown>>('/retrieval/benchmark/integrity'),
  })
}

export function useAnswerLiveSmoke() {
  return useQuery({
    queryKey: ['answer-live-smoke'],
    queryFn: () => api.get<Record<string, unknown>>('/answer/live-smoke'),
  })
}

export function useAdvancedParserCorpus() {
  return useQuery({
    queryKey: ['advanced-parser-corpus'],
    queryFn: () => api.get<Record<string, unknown>>('/advanced-parser-corpus'),
  })
}

export function useOpsDiagnostics() {
  return useQuery({
    queryKey: ['ops-diagnostics'],
    queryFn: () => api.get<Record<string, unknown>>('/ops/diagnostics'),
  })
}

export function useModels() {
  return useQuery({
    queryKey: ['models'],
    queryFn: () => api.get<Record<string, unknown>>('/models'),
  })
}

export function usePlugins() {
  return useQuery({
    queryKey: ['plugins-list'],
    queryFn: () => api.get<{ items: Record<string, unknown>[] }>('/plugins').then((r) => r.items),
  })
}

export function useProcessingProfileMatrix() {
  return useQuery({
    queryKey: ['processing-profile-matrix'],
    queryFn: () => api.get<Record<string, unknown>>('/processing-profiles/matrix'),
  })
}

export function useEvaluationRuns() {
  return useQuery({
    queryKey: ['evaluation-runs'],
    queryFn: () => api.get<Record<string, unknown>>('/evaluations'),
  })
}

export function useEvaluationBaselines() {
  return useQuery({
    queryKey: ['evaluation-baselines'],
    queryFn: () => api.get<Record<string, unknown>>('/evaluations/baselines'),
  })
}

export function useAnswerGen() {
  return useMutation({
    mutationFn: (body: {
      knowledge_base: string
      query: string
      top_k: number
      provider: string
      model: string | null
      answer_provider: string
      answer_model: string | null
      dimensions: number | null
      principal_ids: string[]
      enforce_acl: boolean
    }) => api.post<Record<string, unknown>>('/retrieval/answer', body),
  })
}

export function useCostLatency(knowledgeBase?: string, limit = 20) {
  return useQuery({
    queryKey: ['cost-latency', knowledgeBase, limit],
    queryFn: () => {
      const params = new URLSearchParams()
      if (knowledgeBase) params.set('knowledge_base', knowledgeBase)
      params.set('limit', String(limit))
      return api.get<Record<string, unknown>>(`/observability/cost-latency?${params}`)
    },
  })
}

export function useKnowledgeMap(kbId: string | null) {
  return useQuery({
    queryKey: ['knowledge-map', kbId],
    queryFn: () => api.get<Record<string, unknown>>(`/knowledge-bases/${kbId}/knowledge-map`),
    enabled: !!kbId,
  })
}

// ── P3b: Conversations + feedback ──────────────────────────────────────────

export interface ConversationSummary {
  id: string
  title: string | null
  knowledge_base: string | null
  turn_count: number
  created_at: string
}

export interface ConversationTurn {
  id: string
  turn_index: number
  query: string
  answer: string
  grounding_status: string | null
  citations: Array<{
    citation_id?: string
    document_uri?: string
    chunk_id?: string
    chunk_index?: number
    text_preview?: string
    score?: number
    char_start?: number | null
    char_end?: number | null
    page_number?: number | null
  }>
  created_at: string
}

export interface ConversationDetail {
  id: string
  title: string | null
  knowledge_base: string | null
  turns: ConversationTurn[]
}

export function useConversations() {
  return useQuery({
    queryKey: ['conversations'],
    queryFn: () =>
      api.get<{ items: ConversationSummary[] }>('/conversations').then((r) => r.items),
  })
}

export function useConversation(id: string | null) {
  return useQuery({
    queryKey: ['conversation', id],
    queryFn: () => api.get<ConversationDetail>(`/conversations/${id}`),
    enabled: !!id,
  })
}

export function useCreateConversation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      knowledge_base?: string | null
      title?: string | null
    }) => api.post<{ id: string; title: string | null; knowledge_base: string | null }>(
      '/conversations',
      body,
    ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['conversations'] }),
  })
}

export function useDeleteConversation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete(`/conversations/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['conversations'] }),
  })
}

export function useConversationAnswer() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      body,
    }: {
      id: string
      body: {
        query: string
        knowledge_base?: string | null
        top_k?: number
        provider?: string
        model?: string | null
        history_window?: number
      }
    }) =>
      api.post<{
        turn: ConversationTurn
        grounding_status: string | null
        answer: string
        citations?: ConversationTurn['citations']
      }>(`/conversations/${id}/answer`, body),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['conversation', variables.id] })
      qc.invalidateQueries({ queryKey: ['conversations'] })
    },
  })
}

export function useSubmitFeedback() {
  return useMutation({
    mutationFn: (body: {
      turn_id?: string | null
      rating: -1 | 0 | 1
      reason?: string | null
      query?: string | null
      answer_excerpt?: string | null
    }) => api.post<{ id: string; rating: number }>('/answer-feedback', body),
  })
}

// ── P3c: Usage + budgets ────────────────────────────────────────────────────

export interface UsageRollup {
  event_count: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
  cost_usd: number
  avg_latency_ms: number
  groups?: Array<{
    key: string | null
    count: number
    cost_usd: number
    input_tokens: number
    output_tokens: number
  }>
}

export interface UsageDaily {
  day: string
  count: number
  cost_usd: number
  tokens: number
}

export interface Budget {
  workspace_id: string
  period: string
  limit_usd: number
  alert_threshold_pct: number
  hard_cap: boolean
  last_alert_at: string | null
}

export function useUsage(params?: { since?: string; until?: string; group_by?: string }) {
  const qs = new URLSearchParams()
  if (params?.since) qs.set('since', params.since)
  if (params?.until) qs.set('until', params.until)
  if (params?.group_by) qs.set('group_by', params.group_by)
  const query = qs.toString()
  return useQuery({
    queryKey: ['usage', params],
    queryFn: () => api.get<UsageRollup>(`/usage${query ? `?${query}` : ''}`),
  })
}

export function useUsageTimeseries(days = 30) {
  return useQuery({
    queryKey: ['usage-timeseries', days],
    queryFn: () =>
      api.get<{ items: UsageDaily[] }>(`/usage/timeseries?days=${days}`).then((r) => r.items),
  })
}

export function useBudget() {
  return useQuery({
    queryKey: ['budget'],
    queryFn: () => api.get<{ budget: Budget | null }>('/budgets').then((r) => r.budget),
  })
}

export function useUpsertBudget() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { limit_usd: number; alert_threshold_pct: number; hard_cap: boolean }) =>
      api.put<{ budget: Budget }>('/budgets', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['budget'] }),
  })
}

export function useDeleteBudget() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.delete<void>('/budgets'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['budget'] }),
  })
}

// ── P3e: Admin + backup ────────────────────────────────────────────────────

export interface AdminStatusCounts {
  workspaces: number
  knowledge_bases: number
  sources: number
  conversations: number
  answer_feedback: number
  audit_events: number
}

export function useAdminStatus() {
  return useQuery({
    queryKey: ['admin-status'],
    queryFn: () =>
      api.get<{ counts: AdminStatusCounts }>('/admin/status').then((r) => r.counts),
    refetchInterval: 60_000,
  })
}

export function useRestoreWorkspace() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      api.post<{ status: string; written: Record<string, number> }>('/admin/restore', { payload }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-status'] })
      qc.invalidateQueries({ queryKey: ['knowledge-bases'] })
    },
  })
}

// ── Sources CRUD + ingest trigger ──────────────────────────────────────────

export function useCreateSource() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      plugin_id: string
      config: Record<string, unknown>
      knowledge_base: string
    }) => api.post<{ id: string; kind: string; uri: string }>('/sources', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sources'] }),
  })
}

export function useRunSourceIngest() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      plugin_id: string
      config: Record<string, unknown>
      knowledge_base: string
    }) => api.post<{ task_id: string }>('/sources/run-ingest', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pipeline-runs'] })
      qc.invalidateQueries({ queryKey: ['sources'] })
    },
  })
}

// ── Pipeline run operations ────────────────────────────────────────────────

export function useRetryPipelineRun() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (runId: string) =>
      api.post<{ retried: number }>(`/pipeline-runs/${runId}/retry`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['pipeline-runs'] }),
  })
}

export function useRetryPipelineRunItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (itemId: string) =>
      api.post<Record<string, unknown>>(`/pipeline-run-items/${itemId}/retry`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pipeline-runs'] })
      qc.invalidateQueries({ queryKey: ['pipeline-run-items'] })
    },
  })
}
