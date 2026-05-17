import { createContext, useCallback, useEffect, useState } from 'react'

const TOKEN_KEY = 'ragrig_token'

interface AuthUser {
  user_id: string
  email: string | null
  display_name: string | null
  workspace_id: string
  role: string | null
}

interface AuthContextValue {
  user: AuthUser | null
  token: string | null
  isLoading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, displayName?: string, invitationToken?: string) => Promise<void>
  logout: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)

async function apiPost<T>(path: string, body: unknown, token?: string | null): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(path, { method: 'POST', headers, body: JSON.stringify(body) })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data?.detail ?? data?.error ?? `HTTP ${res.status}`)
  return data as T
}

async function apiGet<T>(path: string, token?: string | null): Promise<T> {
  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(path, { headers })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data?.detail ?? data?.error ?? `HTTP ${res.status}`)
  return data as T
}

interface LoginResponse {
  token: string
  user_id: string
  email: string
  display_name: string | null
  workspace_id: string
  role: string | null
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY))
  const [user, setUser] = useState<AuthUser | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const checkSession = async () => {
      if (!token) {
        if (!cancelled) setIsLoading(false)
        return
      }
      try {
        const me = await apiGet<AuthUser>('/auth/me', token)
        if (!cancelled) setUser(me)
      } catch {
        if (!cancelled) {
          localStorage.removeItem(TOKEN_KEY)
          setToken(null)
          setUser(null)
        }
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }
    checkSession()
    return () => {
      cancelled = true
    }
  }, [token])

  const _storeAuth = useCallback((resp: LoginResponse) => {
    localStorage.setItem(TOKEN_KEY, resp.token)
    setToken(resp.token)
    setUser({
      user_id: resp.user_id,
      email: resp.email,
      display_name: resp.display_name,
      workspace_id: resp.workspace_id,
      role: resp.role,
    })
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const resp = await apiPost<LoginResponse>('/auth/login', { email, password })
    _storeAuth(resp)
  }, [_storeAuth])

  const register = useCallback(async (email: string, password: string, displayName?: string, invitationToken?: string) => {
    const resp = await apiPost<LoginResponse>('/auth/register', {
      email,
      password,
      display_name: displayName || undefined,
      invitation_token: invitationToken || undefined,
    })
    _storeAuth(resp)
  }, [_storeAuth])

  const logout = useCallback(async () => {
    if (token) {
      await apiPost('/auth/logout', {}, token).catch(() => {})
    }
    localStorage.removeItem(TOKEN_KEY)
    setToken(null)
    setUser(null)
  }, [token])

  return (
    <AuthContext.Provider value={{ user, token, isLoading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  )
}
