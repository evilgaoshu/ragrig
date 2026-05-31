import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from './client'

function response(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response
}

function noContentResponse(): Response {
  return {
    ok: true,
    status: 204,
    json: vi.fn().mockRejectedValue(new Error('no body')),
  } as unknown as Response
}

function fetchMock() {
  return vi.mocked(fetch)
}

describe('api client', () => {
  beforeEach(() => {
    window.localStorage.clear()
    window.history.replaceState({}, '', '/')
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('sends JSON requests with content type and serialized body', async () => {
    fetchMock().mockResolvedValueOnce(response({ ok: true }))

    const result = await api.post<{ ok: boolean }>('/knowledge-bases', { name: 'docs' })

    expect(result).toEqual({ ok: true })
    expect(fetch).toHaveBeenCalledWith('/knowledge-bases', {
      method: 'POST',
      body: JSON.stringify({ name: 'docs' }),
      headers: {
        'Content-Type': 'application/json',
      },
    })
  })

  it('adds bearer authorization when a token exists', async () => {
    window.localStorage.setItem('ragrig_token', 'rag_live_test')
    fetchMock().mockResolvedValueOnce(response({ items: [] }))

    await api.get('/knowledge-bases')

    expect(fetch).toHaveBeenCalledWith('/knowledge-bases', {
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer rag_live_test',
      },
    })
  })

  it('returns undefined for 204 responses without reading JSON', async () => {
    const res = noContentResponse()
    fetchMock().mockResolvedValueOnce(res)

    await expect(api.delete('/auth/api-keys/key-1')).resolves.toBeUndefined()
    expect(res.json).not.toHaveBeenCalled()
  })

  it('clears stale tokens on non-auth 401 responses', async () => {
    window.history.replaceState({}, '', '/login')
    window.localStorage.setItem('ragrig_token', 'expired')
    fetchMock().mockResolvedValueOnce(response({ detail: 'Not authenticated' }, 401))

    await expect(api.get('/knowledge-bases')).rejects.toThrow('Not authenticated')

    expect(window.localStorage.getItem('ragrig_token')).toBeNull()
  })

  it('preserves tokens for auth endpoint failures', async () => {
    window.localStorage.setItem('ragrig_token', 'existing')
    fetchMock().mockResolvedValueOnce(response({ detail: 'Bad credentials' }, 401))

    await expect(api.post('/auth/login', { email: 'a@example.com' })).rejects.toThrow(
      'Bad credentials',
    )

    expect(window.localStorage.getItem('ragrig_token')).toBe('existing')
  })

  it('uses HTTP status fallback when an error response has no detail', async () => {
    fetchMock().mockResolvedValueOnce(response({}, 503))

    await expect(api.get('/health')).rejects.toThrow('HTTP 503')
  })

  it('posts forms without forcing a JSON content type', async () => {
    const form = new FormData()
    form.set('file', new Blob(['hello']), 'guide.txt')
    fetchMock().mockResolvedValueOnce(response({ uploaded: true }))

    await api.postForm('/knowledge-bases/kb/upload', form)

    expect(fetch).toHaveBeenCalledWith('/knowledge-bases/kb/upload', {
      method: 'POST',
      headers: {},
      body: form,
    })
  })
})
