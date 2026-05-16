import { NavLink } from 'react-router-dom'

interface NavItem {
  label: string
  to: string
}

const OPERATE: NavItem[] = [
  { label: 'Overview', to: '/' },
  { label: 'Knowledge Bases', to: '/knowledge-bases' },
  { label: 'Sources', to: '/sources' },
  { label: 'Setup Wizard', to: '/wizard' },
  { label: 'Pipelines', to: '/pipelines' },
  { label: 'Upload', to: '/upload' },
  { label: 'Formats', to: '/formats' },
  { label: 'Sanitizer Coverage', to: '/sanitizer-coverage' },
  { label: 'Sanitizer Drift', to: '/sanitizer-drift' },
  { label: 'Retrieval Benchmark', to: '/retrieval-benchmark' },
  { label: 'Baseline Integrity', to: '/baseline-integrity' },
  { label: 'Answer Live Smoke', to: '/answer-live-smoke' },
  { label: 'Parser Corpus', to: '/parser-corpus' },
  { label: 'Ops Diagnostics', to: '/ops-diagnostics' },
  { label: 'Cost & Latency', to: '/cost-latency' },
  { label: 'Documents', to: '/documents' },
]

const INSPECT: NavItem[] = [
  { label: 'Retrieval Lab', to: '/retrieval-lab' },
  { label: 'Answer Gen', to: '/answer-gen' },
  { label: 'Models', to: '/models' },
  { label: 'Profile Matrix', to: '/profile-matrix' },
  { label: 'Plugins', to: '/plugins' },
  { label: 'Evaluation', to: '/evaluation' },
  { label: 'Settings', to: '/settings' },
]

function NavGroup({ label, items }: { label: string; items: NavItem[] }) {
  return (
    <>
      <div className="mt-4 mb-1 px-3 text-[10px] font-bold uppercase tracking-widest text-gray-400">
        {label}
      </div>
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === '/'}
          className={({ isActive }) =>
            `block px-3 py-1.5 rounded text-[13px] transition-colors ${
              isActive
                ? 'bg-brand/10 text-brand font-semibold'
                : 'text-gray-700 hover:bg-gray-100'
            }`
          }
        >
          {item.label}
        </NavLink>
      ))}
    </>
  )
}

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside className="w-52 shrink-0 border-r border-gray-200 bg-white flex flex-col overflow-y-auto">
        <div className="px-3 pt-4 pb-2">
          <div className="text-[15px] font-bold text-brand">RAGRig</div>
          <div className="text-[10px] text-gray-400">source-governed RAG</div>
        </div>
        <nav className="flex-1 px-2 pb-4">
          <NavGroup label="Operate" items={OPERATE} />
          <NavGroup label="Inspect" items={INSPECT} />
        </nav>
        <div className="px-3 pb-3 text-[11px] text-gray-400">
          <a href="/docs" className="hover:text-brand">Swagger</a>
          {' · '}
          <a href="/console" className="hover:text-brand">Legacy UI</a>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-y-auto bg-gray-50">
        {children}
      </main>
    </div>
  )
}
