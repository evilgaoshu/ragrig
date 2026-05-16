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

export function useModels() {
  return useQuery({
    queryKey: ['models'],
    queryFn: () => api.get<{ embedding_models: unknown[]; rerankers: unknown[] }>('/models'),
  })
}

export function usePlugins() {
  return useQuery({
    queryKey: ['plugins'],
    queryFn: () => api.get<{ items: unknown[] }>('/plugins').then((r) => r.items),
  })
}

export function useEvaluationRuns() {
  return useQuery({
    queryKey: ['evaluation-runs'],
    queryFn: () => api.get<{ runs: unknown[] }>('/evaluations/runs').then((r) => r.runs),
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
