import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { KnowledgeBase, SystemStatus, PipelineRun, RetrievalReport } from './types'

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

export function usePipelineRuns(kbId?: string) {
  return useQuery({
    queryKey: ['pipeline-runs', kbId],
    queryFn: () =>
      api
        .get<{ items: PipelineRun[] }>(`/pipeline-runs${kbId ? `?knowledge_base_id=${kbId}` : ''}`)
        .then((r) => r.items),
    refetchInterval: 10_000,
  })
}

export function useSources() {
  return useQuery({
    queryKey: ['sources'],
    queryFn: () => api.get<{ items: unknown[] }>('/sources').then((r) => r.items),
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
    queryFn: () => api.get<{ items: unknown[] }>('/supported-formats').then((r) => r.items),
  })
}
