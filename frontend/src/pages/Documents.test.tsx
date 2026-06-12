import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Documents from './Documents'

function response(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response
}

function renderDocuments() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <Documents />
    </QueryClientProvider>,
  )
}

const chunk = {
  id: 'chunk-1',
  chunk_index: 0,
  heading: null,
  char_start: 0,
  char_end: 26,
  page_number: null,
  text: 'Alpha beta gamma delta.',
  metadata: {
    chunk_template_id: 'char_window_v1',
    template_parameters: { chunk_size: 500, chunk_overlap: 50 },
    split_reason: 'window_boundary',
    source_block_type: 'unknown',
    source_block_id: 'block-1',
    split_explanation: 'char_window_v1 applied window_boundary.',
  },
}

describe('Documents chunk review', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path === '/documents') {
        return Promise.resolve(response({
          items: [{
            id: 'doc-1',
            knowledge_base: 'demo',
            uri: 'file:///guide.txt',
            source_uri: 'file:///guide.txt',
            mime_type: 'text/plain',
            content_hash: 'hash',
            metadata: {},
            acl_summary: {},
            latest_version: {
              id: 'version-1',
              version_number: 1,
              parser_name: 'text',
              parser_config: {},
              metadata: {},
              text_preview: chunk.text,
              chunk_count: 1,
              created_at: '2026-06-11T00:00:00Z',
            },
          }],
        }))
      }
      if (path === '/document-versions/version-1/chunk-review') {
        return Promise.resolve(response({
          items: [chunk],
          override: null,
          index_status: { status: 'current', reindex_required: false },
          edit_supported: true,
          edit_limitation: null,
        }))
      }
      if (path === '/document-versions/version-1/chunk-override' && init?.method === 'PUT') {
        return Promise.resolve(response({
          override: { revision: 1, status: 'pending_reindex' },
          index_status: { status: 'stale', reindex_required: true },
        }))
      }
      return Promise.resolve(response({ detail: `unexpected ${path}` }, 404))
    }))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('renders explainability fields and saves a real split override request', async () => {
    renderDocuments()

    await userEvent.click(await screen.findByRole('button', { name: /guide\.txt/ }))
    await userEvent.click(screen.getByRole('button', { name: /Chunks \(1\)/ }))

    expect(await screen.findByText('char_window_v1')).toBeInTheDocument()
    expect(screen.getByText('window_boundary')).toBeInTheDocument()
    expect(screen.getByText('char_window_v1 applied window_boundary.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Split' }))
    expect(screen.getByText('1 pending change(s)')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() => {
      const request = vi.mocked(fetch).mock.calls.find(
        ([path, init]) =>
          path === '/document-versions/version-1/chunk-override' && init?.method === 'PUT',
      )
      expect(request).toBeTruthy()
      const body = JSON.parse(String(request?.[1]?.body))
      expect(body.chunks).toHaveLength(2)
      expect(body.chunks[0].split_reason).toBe('manual_split')
      expect(body.operations[0].operation).toBe('split')
    })
  })
})
