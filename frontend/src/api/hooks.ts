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
