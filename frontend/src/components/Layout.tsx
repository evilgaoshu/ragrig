import { useEffect, useRef, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { useAuth } from '../contexts/useAuth'

interface NavItem {
  label: string
  to: string
}

const NAV_GROUPS: Array<{ label: string; items: NavItem[] }> = [
  {
    label: 'Operate',
    items: [
      { label: 'Overview', to: '/' },
      { label: 'Pipelines', to: '/pipelines' },
      { label: 'Datasets', to: '/knowledge-bases' },
      { label: 'Documents', to: '/documents' },
      { label: 'Sources', to: '/sources' },
      { label: 'Sinks', to: '/sinks' },
    ],
  },
  {
    label: 'Configure',
    items: [
      { label: 'Pipeline profiles', to: '/pipeline-profiles' },
      { label: 'AI Providers', to: '/models' },
      { label: 'Notifications', to: '/notifications' },
      { label: 'Plugins', to: '/plugins' },
    ],
  },
  {
    label: 'Inspect',
    items: [
      { label: 'Retrieval Lab', to: '/retrieval-lab' },
      { label: 'Evaluations', to: '/evaluation' },
      { label: 'Understanding', to: '/understanding' },
      { label: 'Knowledge Map', to: '/knowledge-map' },
      { label: 'Conversations', to: '/conversations' },
      { label: 'Conflicts', to: '/conflicts' },
    ],
  },
  {
    label: 'Quality',
    items: [
      { label: 'Quality Suite', to: '/quality' },
      { label: 'Retrieval Benchmark', to: '/retrieval-benchmark' },
      { label: 'Sanitizer Drift', to: '/sanitizer-drift' },
      { label: 'Parser Corpus', to: '/parser-corpus' },
    ],
  },
  {
    label: 'Admin',
    items: [
      { label: 'Access', to: '/access' },
      { label: 'Usage & Budget', to: '/usage' },
      { label: 'Operations', to: '/operations' },
    ],
  },
]

function NavGroup({ label, items }: { label: string; items: NavItem[] }) {
  return (
    <div className="mt-4">
      <div className="mb-1 px-3 text-[10px] font-bold uppercase tracking-widest text-slate-400">
        {label}
      </div>
      <div className="space-y-0.5">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) =>
              `relative block rounded-lg px-3 py-2 text-[13px] transition-colors ${
                isActive
                  ? 'bg-brand/10 font-semibold text-brand before:absolute before:left-0 before:top-2 before:h-5 before:w-0.5 before:rounded-full before:bg-brand'
                  : 'text-slate-600 hover:bg-blue-50 hover:text-ink'
              }`
            }
          >
            {item.label}
          </NavLink>
        ))}
      </div>
    </div>
  )
}

export default function Layout({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth()
  const accountLabel = user?.display_name ?? user?.email ?? 'User'
  const accountInitial = accountLabel.slice(0, 1).toUpperCase()
  const [accountMenuOpen, setAccountMenuOpen] = useState(false)
  const accountMenuRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    function handlePointerDown(event: PointerEvent) {
      if (!accountMenuRef.current?.contains(event.target as Node)) {
        setAccountMenuOpen(false)
      }
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setAccountMenuOpen(false)
      }
    }

    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [])

  return (
    <div className="flex h-screen overflow-hidden bg-canvas text-ink">
      <aside className="flex w-64 shrink-0 flex-col overflow-y-auto border-r border-line bg-white/90">
        <div className="px-4 pb-3 pt-4">
          <div className="flex items-center gap-3">
            <img src="/ragrig-icon.svg" alt="" className="h-9 w-9 rounded-lg" />
            <div>
              <div className="text-[15px] font-bold text-ink">RAGRig</div>
              <div className="text-[11px] text-muted">Traceable RAG console</div>
            </div>
          </div>
        </div>
        <nav className="flex-1 px-3 pb-4">
          {NAV_GROUPS.map((group) => (
            <NavGroup key={group.label} label={group.label} items={group.items} />
          ))}
        </nav>
      </aside>

      <main className="min-w-0 flex-1 overflow-y-auto">
        <div className="sticky top-0 z-10 flex min-h-14 items-center justify-between gap-3 border-b border-line bg-canvas/90 px-6 backdrop-blur">
          <div className="text-xs text-muted">ragrig / workspace / demo</div>
          <div className="flex items-center gap-2">
            <input
              type="search"
              placeholder="Search docs, runs, chunks"
              className="h-9 w-72 max-w-[40vw] rounded-lg border border-line bg-white px-3 text-sm outline-none focus:ring-2 focus:ring-brand/30"
            />
            <button className="h-9 rounded-lg border border-line bg-white px-3 text-sm font-medium text-slate-600 hover:bg-blue-50">
              中文
            </button>
            {user ? (
              <div className="relative" ref={accountMenuRef}>
                <button
                  type="button"
                  aria-haspopup="menu"
                  aria-expanded={accountMenuOpen}
                  onClick={() => setAccountMenuOpen((open) => !open)}
                  className="flex h-9 items-center gap-2 rounded-lg border border-line bg-white py-1 pl-1 pr-2.5 text-left hover:bg-blue-50"
                >
                  <div className="grid h-7 w-7 place-items-center rounded-full bg-brand text-[11px] font-bold text-white">
                    {accountInitial}
                  </div>
                  <div className="hidden min-w-0 sm:block">
                    <div className="max-w-32 truncate text-xs font-semibold text-ink">{accountLabel}</div>
                    <div className="text-[10px] leading-none text-muted">{user.role ?? 'member'}</div>
                  </div>
                  <span className="text-[11px] text-muted">▾</span>
                </button>
                {accountMenuOpen ? (
                  <div
                    role="menu"
                    className="absolute right-0 top-11 z-30 w-56 rounded-xl border border-line bg-white p-1.5 shadow-[0_18px_50px_rgba(15,23,42,0.18)]"
                  >
                    <div className="mb-1 border-b border-line px-2.5 pb-2 pt-1.5">
                      <div className="truncate text-xs font-bold text-ink">{accountLabel}</div>
                      <div className="text-[11px] text-muted">{user.role ?? 'member'} · demo workspace</div>
                    </div>
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => setAccountMenuOpen(false)}
                      className="flex h-9 w-full items-center justify-between rounded-lg px-2.5 text-sm font-medium text-ink hover:bg-blue-50 hover:text-brand"
                    >
                      Personal info
                      <span className="text-xs text-muted">⌘I</span>
                    </button>
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => setAccountMenuOpen(false)}
                      className="flex h-9 w-full items-center justify-between rounded-lg px-2.5 text-sm font-medium text-ink hover:bg-blue-50 hover:text-brand"
                    >
                      Change password
                      <span className="text-xs text-muted">•••</span>
                    </button>
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        setAccountMenuOpen(false)
                        logout()
                      }}
                      className="flex h-9 w-full items-center justify-between rounded-lg px-2.5 text-sm font-medium text-red-600 hover:bg-red-50"
                    >
                      Sign out
                      <span className="text-xs">↩</span>
                    </button>
                  </div>
                ) : null}
              </div>
            ) : (
              <NavLink
                to="/login"
                className="flex h-9 items-center rounded-lg border border-line bg-white px-3 text-sm font-medium text-slate-600 hover:bg-blue-50 hover:text-brand"
              >
                Sign in
              </NavLink>
            )}
          </div>
        </div>
        {children}
      </main>
    </div>
  )
}
