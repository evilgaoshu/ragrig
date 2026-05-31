import type { ComponentProps } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ProtectedRoute from '../components/ProtectedRoute'
import { AuthContext, AuthProvider } from './AuthContext'
import { useAuth } from './useAuth'

const USER = {
  user_id: 'user-1',
  email: 'alice@example.com',
  display_name: 'Alice',
  workspace_id: 'workspace-1',
  role: 'admin',
}

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

function AuthProbe() {
  const { user, token, isLoading, login, logout, register } = useAuth()
  return (
    <div>
      <div data-testid="loading">{String(isLoading)}</div>
      <div data-testid="user">{user?.email ?? 'none'}</div>
      <div data-testid="token">{token ?? 'none'}</div>
      <button type="button" onClick={() => login('alice@example.com', 'Password1!')}>
        Login
      </button>
      <button
        type="button"
        onClick={() => register('alice@example.com', 'Password1!', 'Alice', 'invite-1')}
      >
        Register
      </button>
      <button type="button" onClick={() => logout()}>
        Logout
      </button>
    </div>
  )
}

function renderAuthProvider() {
  return render(
    <AuthProvider>
      <AuthProbe />
    </AuthProvider>,
  )
}

describe('AuthProvider', () => {
  beforeEach(() => {
    window.localStorage.clear()
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('hydrates the active session from /auth/me', async () => {
    window.localStorage.setItem('ragrig_token', 'session-token')
    fetchMock().mockResolvedValueOnce(response(USER))

    renderAuthProvider()

    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'))
    expect(screen.getByTestId('user')).toHaveTextContent('alice@example.com')
    expect(screen.getByTestId('token')).toHaveTextContent('session-token')
    expect(fetch).toHaveBeenCalledWith('/auth/me', {
      headers: { Authorization: 'Bearer session-token' },
    })
  })

  it('clears stale tokens when session hydration fails', async () => {
    window.localStorage.setItem('ragrig_token', 'stale-token')
    fetchMock().mockResolvedValueOnce(response({ detail: 'Not authenticated' }, 401))

    renderAuthProvider()

    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'))
    expect(screen.getByTestId('user')).toHaveTextContent('none')
    expect(screen.getByTestId('token')).toHaveTextContent('none')
    expect(window.localStorage.getItem('ragrig_token')).toBeNull()
  })

  it('stores login responses in context and localStorage', async () => {
    fetchMock()
      .mockResolvedValueOnce(response({ detail: 'No session' }, 401))
      .mockResolvedValueOnce(response({ ...USER, token: 'login-token' }))
      .mockResolvedValueOnce(response(USER))

    renderAuthProvider()
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'))

    await userEvent.click(screen.getByRole('button', { name: 'Login' }))

    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('alice@example.com'))
    expect(screen.getByTestId('token')).toHaveTextContent('login-token')
    expect(window.localStorage.getItem('ragrig_token')).toBe('login-token')
    expect(fetch).toHaveBeenNthCalledWith(2, '/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: 'alice@example.com', password: 'Password1!' }),
    })
  })

  it('passes invitation tokens during registration', async () => {
    fetchMock()
      .mockResolvedValueOnce(response({ detail: 'No session' }, 401))
      .mockResolvedValueOnce(response({ ...USER, token: 'register-token' }))
      .mockResolvedValueOnce(response(USER))

    renderAuthProvider()
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'))

    await userEvent.click(screen.getByRole('button', { name: 'Register' }))

    await waitFor(() => expect(screen.getByTestId('token')).toHaveTextContent('register-token'))
    expect(fetch).toHaveBeenNthCalledWith(2, '/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: 'alice@example.com',
        password: 'Password1!',
        display_name: 'Alice',
        invitation_token: 'invite-1',
      }),
    })
  })

  it('logs out server-side and clears local auth state', async () => {
    window.localStorage.setItem('ragrig_token', 'session-token')
    fetchMock()
      .mockResolvedValueOnce(response(USER))
      .mockResolvedValueOnce(noContentResponse())
      .mockResolvedValueOnce(response({ detail: 'No session' }, 401))

    renderAuthProvider()
    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('alice@example.com'))

    await userEvent.click(screen.getByRole('button', { name: 'Logout' }))

    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('none'))
    expect(screen.getByTestId('token')).toHaveTextContent('none')
    expect(window.localStorage.getItem('ragrig_token')).toBeNull()
    expect(fetch).toHaveBeenNthCalledWith(2, '/auth/logout', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer session-token',
      },
      body: JSON.stringify({}),
    })
  })
})

describe('ProtectedRoute', () => {
  const baseContext = {
    user: null,
    token: null,
    isLoading: false,
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
  }

  function renderProtectedRoute(value: ComponentProps<typeof AuthContext.Provider>['value']) {
    return render(
      <AuthContext.Provider value={value}>
        <MemoryRouter initialEntries={['/private']}>
          <Routes>
            <Route
              path="/private"
              element={
                <ProtectedRoute>
                  <div>Private page</div>
                </ProtectedRoute>
              }
            />
            <Route path="/login" element={<div>Login page</div>} />
          </Routes>
        </MemoryRouter>
      </AuthContext.Provider>,
    )
  }

  it('shows a loading state while auth is pending', () => {
    renderProtectedRoute({ ...baseContext, isLoading: true })

    expect(screen.getByText('Loading…')).toBeInTheDocument()
  })

  it('redirects anonymous users to login', () => {
    renderProtectedRoute(baseContext)

    expect(screen.getByText('Login page')).toBeInTheDocument()
  })

  it('renders children for authenticated users', () => {
    renderProtectedRoute({ ...baseContext, user: USER, token: 'session-token' })

    expect(screen.getByText('Private page')).toBeInTheDocument()
  })
})
