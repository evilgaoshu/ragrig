import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AnswerGen from './AnswerGen'

function response(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response
}

function renderAnswerGen() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <AnswerGen />
    </QueryClientProvider>,
  )
}

describe('AnswerGen citation UX', () => {
  const scrollIntoView = vi.fn()

  beforeEach(() => {
    Element.prototype.scrollIntoView = scrollIntoView
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const path = String(input)
      if (path === '/knowledge-bases') {
        return Promise.resolve(response({
          items: [{
            id: 'kb-1',
            name: 'demo',
            workspace_id: 'workspace-1',
            document_count: 1,
            chunk_count: 1,
            embedding_model: 'hash-8d',
            created_at: '2026-06-12T00:00:00Z',
          }],
        }))
      }
      if (path === '/retrieval/answer') {
        return Promise.resolve(response({
          answer: 'Grounded fact [cit-1] and another [cit-2].',
          citations: [
            {
              citation_id: 'cit-1',
              document_uri: 'file:///guide.pdf',
              chunk_id: 'chunk-1',
              chunk_index: 0,
              text_preview: 'First source preview',
              score: 0.987,
              char_start: 120,
              char_end: 180,
              page_number: 3,
              metadata_summary: { section: 'Overview' },
            },
            {
              citation_id: 'cit-2',
              document_uri: 'file:///notes.md',
              chunk_id: 'chunk-2',
              chunk_index: 1,
              text_preview: 'Second source preview',
              score: 0.8,
              char_start: null,
              char_end: null,
              page_number: null,
              metadata_summary: {},
            },
          ],
          model: 'deterministic',
          provider: 'deterministic-local',
          grounding_status: 'grounded',
        }))
      }
      return Promise.resolve(response({ detail: `unexpected ${path}` }, 404))
    }))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    scrollIntoView.mockReset()
  })

  it('renders inline citations and highlights the matching source span', async () => {
    renderAnswerGen()
    await screen.findByRole('option', { name: 'demo' })
    await userEvent.selectOptions(screen.getByLabelText('Knowledge base'), 'demo')
    await userEvent.type(screen.getByLabelText('Query'), 'What is grounded?')
    await userEvent.click(screen.getByRole('button', { name: 'Generate answer' }))

    const inline = await screen.findByRole('button', { name: 'Open citation 1' })
    expect(screen.getByText('page 3')).toBeInTheDocument()
    expect(screen.getByText('chars 120:180')).toBeInTheDocument()
    expect(screen.getByText('chunk chunk-1')).toBeInTheDocument()
    expect(screen.getByText('First source preview')).toBeInTheDocument()

    await userEvent.click(inline)
    const reference = document.getElementById('reference-cit-1')
    await waitFor(() => expect(reference).toHaveAttribute('aria-current', 'true'))
    expect(scrollIntoView).toHaveBeenCalled()
    expect(reference).toHaveFocus()
  })
})
