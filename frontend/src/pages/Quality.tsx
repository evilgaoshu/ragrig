import { useState } from 'react'
import { Button } from '../components/ui'
import { ConsolePage, DataTable, MetricCard, Panel, StatusPill } from '../components/console'

const CHECKS = [
  { id: 'retrieval', name: 'Retrieval benchmark', owner: 'retrieval', last: '14m ago', result: 'pass', detail: 'baseline +2.1%' },
  { id: 'graph-console', name: 'Graph console runbook', owner: 'graph ops', last: '18m ago', result: 'pass', detail: 'feedback suppression verified' },
  { id: 'sanitizer', name: 'Sanitizer coverage', owner: 'security', last: '31m ago', result: 'warn', detail: '2 formats below target' },
  { id: 'parser', name: 'Parser corpus', owner: 'ingestion', last: '2h ago', result: 'pass', detail: '41/41 fixtures' },
  { id: 'answer', name: 'Answer live smoke', owner: 'answer', last: '4h ago', result: 'pass', detail: 'citations valid' },
]

export default function Quality() {
  const [selectedId, setSelectedId] = useState(CHECKS[0].id)
  const [message, setMessage] = useState('')
  const selected = CHECKS.find((check) => check.id === selectedId) ?? CHECKS[0]

  return (
    <ConsolePage
      title="Quality Suite"
      description="A single operational view for retrieval, sanitizer, parser, and answer smoke quality gates."
      actions={<Button onClick={() => setMessage('Nightly quality suite queued for all checks.')}>Run suite</Button>}
    >
      {message && <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-700">{message}</div>}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard label="Golden score" value="92.4" sub="retrieval baseline" />
        <MetricCard label="Graph rehearsal" value="pass" sub="demo console loop" tone="ok" />
        <MetricCard label="Coverage" value="96%" sub="sanitizer contract" tone="ok" />
        <MetricCard label="Regressions" value="2" sub="needs review" tone="warn" />
      </div>
      <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <Panel title="Quality gates" description="Click a check to inspect commands, artifacts, and owner actions.">
          <DataTable
            rows={CHECKS}
            getKey={(row) => row.id}
            onRowClick={(row) => setSelectedId(row.id)}
            columns={[
              { key: 'name', label: 'Check', render: (row) => <div><div className="font-medium text-ink">{row.name}</div><div className="text-xs text-muted">{row.owner}</div></div> },
              { key: 'last', label: 'Last run', render: (row) => row.last },
              { key: 'detail', label: 'Detail', render: (row) => row.detail },
              { key: 'result', label: 'Result', render: (row) => <StatusPill tone={row.result === 'pass' ? 'ok' : 'warn'}>{row.result}</StatusPill> },
              { key: 'actions', label: 'Actions', align: 'right', render: (row) => <button onClick={() => setMessage(`${row.name} queued.`)} className="rounded-lg border border-line px-2 py-1 text-xs font-medium text-brand hover:bg-blue-50">Run</button> },
            ]}
          />
        </Panel>
        <Panel
          title={`${selected.name} detail`}
          description={`${selected.owner} · last run ${selected.last}`}
          actions={<Button variant="secondary" onClick={() => setMessage(`${selected.name} artifact copied to clipboard.`)}>Copy command</Button>}
        >
          <div className="space-y-3">
            <div className="rounded-lg border border-line bg-white p-3">
              <div className="text-xs font-semibold uppercase tracking-wider text-muted">Result</div>
              <div className="mt-2 text-sm text-slate-700">{selected.detail}</div>
            </div>
            <div className="rounded-lg border border-blue-100 bg-blue-50/45 p-3 font-mono text-xs text-slate-700">
              scripts/{selected.id === 'retrieval' ? 'retrieval_benchmark.py' : selected.id === 'graph-console' ? 'demo_graph_console_smoke.py' : selected.id === 'sanitizer' ? 'sanitizer_coverage.py' : selected.id === 'parser' ? 'advanced_parser_corpus_check.py' : 'answer_live_smoke.py'}
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-lg border border-blue-100 bg-blue-50/45 p-3 text-sm">Artifact retention: 30d</div>
              <div className="rounded-lg border border-blue-100 bg-blue-50/45 p-3 text-sm">PR gate: {selected.result === 'pass' ? 'non-blocking' : 'requires owner review'}</div>
              <div className="rounded-lg border border-blue-100 bg-blue-50/45 p-3 text-sm">Evidence: {selected.id === 'graph-console' ? 'Graph context + feedback + cleanup' : 'standard quality artifact'}</div>
              <div className="rounded-lg border border-blue-100 bg-blue-50/45 p-3 text-sm">Owner action: {selected.id === 'graph-console' ? 'rehearse demo before release' : 'review failed gate'}</div>
            </div>
          </div>
        </Panel>
      </div>
    </ConsolePage>
  )
}
