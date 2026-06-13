import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Models from './Models'

function response(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response
}

function renderModels() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <Models />
    </QueryClientProvider>,
  )
}

describe('Models stage model policy', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path === '/knowledge-bases') {
        return Promise.resolve(response({
          items: [{
            id: 'kb-1',
            name: 'policy-kb',
            workspace_id: 'workspace-1',
            document_count: 1,
            chunk_count: 1,
            embedding_model: 'hash-8d',
            created_at: '2026-06-12T00:00:00Z',
          }],
        }))
      }
      if (path === '/knowledge-bases/kb-1/stage-model-policy' && init?.method === 'PUT') {
        return Promise.resolve(response({
          status: 'saved',
          knowledge_base_id: 'kb-1',
          knowledge_base: 'policy-kb',
          stages: ['answer'],
          policy: {
            answer: {
              provider: 'deterministic-local',
              model: 'edited-answer',
              has_config: true,
              config_keys: ['api_key'],
            },
          },
        }))
      }
      if (path === '/knowledge-bases/kb-1/stage-model-policy') {
        return Promise.resolve(response({
          knowledge_base_id: 'kb-1',
          knowledge_base: 'policy-kb',
          stages: ['answer'],
          policy: {
            answer: {
              provider: 'deterministic-local',
              model: 'policy-answer',
              budget_hint_usd: 0.01,
              has_config: true,
              config_keys: ['api_key'],
            },
          },
        }))
      }
      return Promise.resolve(response({ detail: `unexpected ${path}` }, 404))
    }))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('loads redacted policy and saves real JSON without secret summaries', async () => {
    renderModels()

    await waitFor(() => expect(screen.getByLabelText('Stage policy knowledge base')).toHaveValue('kb-1'))
    expect(await screen.findByText('policy-answer')).toBeInTheDocument()
    expect(screen.getByText('api_key')).toBeInTheDocument()
    const editor = screen.getByLabelText('Stage model policy JSON')
    expect(editor).not.toHaveValue(expect.stringContaining('api_key'))

    fireEvent.change(editor, {
      target: {
        value: JSON.stringify({
          answer: {
            provider: 'deterministic-local',
            model: 'edited-answer',
          },
        }),
      },
    })
    await userEvent.click(screen.getByRole('button', { name: 'Save stage policy' }))

    await waitFor(() => {
      const calls = vi.mocked(fetch).mock.calls
      const put = calls.find(([path, init]) =>
        path === '/knowledge-bases/kb-1/stage-model-policy' && init?.method === 'PUT')
      expect(put).toBeTruthy()
      expect(JSON.parse(String(put?.[1]?.body))).toEqual({
        policy: {
          answer: {
            provider: 'deterministic-local',
            model: 'edited-answer',
          },
        },
      })
    })
  })
})
