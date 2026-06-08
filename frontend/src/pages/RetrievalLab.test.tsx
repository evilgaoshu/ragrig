import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import RetrievalLab from './RetrievalLab'

function response(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response
}

function fetchMock() {
  return vi.mocked(fetch)
}

function renderRetrievalLab() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <RetrievalLab />
    </QueryClientProvider>,
  )
}

const kb = {
  id: 'kb-1',
  name: 'local-pilot-demo-rc',
  workspace_id: 'workspace-1',
  document_count: 2,
  chunk_count: 2,
  embedding_model: 'hash-8d',
  created_at: '2026-06-08T00:00:00Z',
}

const preferences = {
  mode: 'rerank',
  lexical_weight: 0.3,
  vector_weight: 0.7,
  candidate_k: 20,
  reranker_provider: 'reranker.bge',
  reranker_model: 'BAAI/bge-reranker-v2-m3',
  graph_weight: 0.35,
  graph_depth: 1,
}

const rerankReport = {
  knowledge_base: 'local-pilot-demo-rc',
  query: 'citations',
  top_k: 8,
  provider: 'deterministic-local',
  model: 'hash-8d',
  total_results: 2,
  graph_context: {},
  cost_latency: { phase_latencies_ms: { rerank_ms: 12.5 } },
  rerank_trace: {
    status: 'applied',
    provider: 'reranker.jina',
    model: 'jina-reranker-m0',
    candidate_count: 2,
    changed_count: 1,
    latency_ms: 12.5,
    before: [
      { rank: 1, document_uri: 'old-top.md', score: 0.61 },
      { rank: 2, document_uri: 'new-top.md', score: 0.44 },
    ],
    after: [
      { rank: 1, original_rank: 2, document_uri: 'new-top.md', score: 0.93 },
      { rank: 2, original_rank: 1, document_uri: 'old-top.md', score: 0.22 },
    ],
  },
  results: [
    {
      chunk_id: 'chunk-2',
      document_id: 'doc-2',
      document_version_id: 'ver-2',
      document_uri: 'new-top.md',
      source_uri: null,
      text: 'new top evidence',
      text_preview: 'new top evidence',
      distance: 0.2,
      score: 0.93,
      chunk_metadata: {},
      rank_stage_trace: {
        stages: [
          { stage: 'vector', score: 0.44 },
          {
            stage: 'rerank',
            score: 0.93,
            original_rank: 2,
            new_rank: 1,
            reranker: 'reranker.jina',
            model: 'jina-reranker-m0',
          },
        ],
        final_source: 'rerank',
      },
    },
  ],
}

describe('RetrievalLab reranker controls', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path === '/knowledge-bases') {
        return Promise.resolve(response({ items: [kb] }))
      }
      if (path === '/knowledge-bases/kb-1/retrieval-preferences') {
        return Promise.resolve(response({ knowledge_base_id: 'kb-1', knowledge_base: kb.name, preferences }))
      }
      if (path === '/retrieval/search' && init?.method === 'POST') {
        return Promise.resolve(response(rerankReport))
      }
      return Promise.resolve(response({ detail: `unexpected ${path}` }, 404))
    }))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('submits configurable reranker provider settings and renders before/after ranking', async () => {
    renderRetrievalLab()

    await waitFor(() => expect(screen.getByLabelText('Knowledge base')).toHaveValue('kb-1'))
    await userEvent.selectOptions(screen.getByLabelText('Reranker provider'), 'reranker.jina')
    await userEvent.clear(screen.getByLabelText('Reranker model'))
    await userEvent.type(screen.getByLabelText('Reranker model'), 'jina-reranker-m0')
    await userEvent.clear(screen.getByLabelText('Candidate K'))
    await userEvent.type(screen.getByLabelText('Candidate K'), '12')
    await userEvent.click(screen.getByRole('button', { name: 'Search' }))

    await waitFor(() => {
      const searchCall = fetchMock().mock.calls.find(([path]) => path === '/retrieval/search')
      expect(searchCall).toBeTruthy()
      const body = JSON.parse(String(searchCall?.[1]?.body))
      expect(body.reranker_provider).toBe('reranker.jina')
      expect(body.reranker_model).toBe('jina-reranker-m0')
      expect(body.candidate_k).toBe(12)
    })

    await waitFor(() => expect(screen.getAllByText('reranker.jina').length).toBeGreaterThan(0))
    expect(screen.getAllByText('12.5 ms').length).toBeGreaterThan(0)
    expect(screen.getAllByText('1 changed').length).toBeGreaterThan(0)

    const beforePanel = screen.getByRole('region', { name: 'Before rerank' })
    expect(within(beforePanel).getByText('#2')).toBeInTheDocument()
    expect(within(beforePanel).getByText('new-top.md')).toBeInTheDocument()

    const afterPanel = screen.getByRole('region', { name: 'After rerank' })
    expect(within(afterPanel).getByText('#1')).toBeInTheDocument()
    expect(within(afterPanel).getByText('new-top.md')).toBeInTheDocument()
    expect(within(afterPanel).getByText('was #2')).toBeInTheDocument()
  })
})
