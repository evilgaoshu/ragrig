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

  return (
    <div className="flex h-screen overflow-hidden bg-canvas text-ink">
      <aside className="flex w-64 shrink-0 flex-col overflow-y-auto border-r border-line bg-white/90">
        <div className="px-4 pb-3 pt-4">
          <div className="flex items-center gap-3">
            <img src="/assets/ragrig-icon.svg" alt="" className="h-9 w-9 rounded-lg" />
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
        <div className="border-t border-line px-4 py-3">
          {user && (
            <div className="mb-3">
              <div className="truncate text-xs font-medium text-ink">
                {user.display_name ?? user.email ?? 'User'}
              </div>
              <div className="truncate text-[11px] text-muted">{user.role}</div>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted">
            <a href="/docs" className="hover:text-brand">Swagger</a>
            <span>·</span>
            <a href="/console" className="hover:text-brand">Legacy UI</a>
            {user && (
              <>
                <span>·</span>
                <button onClick={() => logout()} className="hover:text-red-600">
                  Sign out
                </button>
              </>
            )}
          </div>
        </div>
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
          </div>
        </div>
        {children}
      </main>
    </div>
  )
}
