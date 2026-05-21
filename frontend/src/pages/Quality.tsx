import { ConsolePage, DataTable, MetricCard, Panel, StatusPill } from '../components/console'

const CHECKS = [
  { id: 'retrieval', name: 'Retrieval benchmark', owner: 'retrieval', last: '14m ago', result: 'pass', detail: 'baseline +2.1%' },
  { id: 'sanitizer', name: 'Sanitizer coverage', owner: 'security', last: '31m ago', result: 'warn', detail: '2 formats below target' },
  { id: 'parser', name: 'Parser corpus', owner: 'ingestion', last: '2h ago', result: 'pass', detail: '41/41 fixtures' },
  { id: 'answer', name: 'Answer live smoke', owner: 'answer', last: '4h ago', result: 'pass', detail: 'citations valid' },
]

export default function Quality() {
  return (
    <ConsolePage title="Quality Suite" description="A single operational view for retrieval, sanitizer, parser, and answer smoke quality gates.">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard label="Golden score" value="92.4" sub="retrieval baseline" />
        <MetricCard label="Coverage" value="96%" sub="sanitizer contract" tone="ok" />
        <MetricCard label="Regressions" value="2" sub="needs review" tone="warn" />
        <MetricCard label="Answer smoke" value="pass" sub="live provider path" tone="ok" />
      </div>
      <Panel title="Quality gates" description="These are administrator-facing checks, not separate product settings.">
        <DataTable
          rows={CHECKS}
          getKey={(row) => row.id}
          columns={[
            { key: 'name', label: 'Check', render: (row) => <div><div className="font-medium text-ink">{row.name}</div><div className="text-xs text-muted">{row.owner}</div></div> },
            { key: 'last', label: 'Last run', render: (row) => row.last },
            { key: 'detail', label: 'Detail', render: (row) => row.detail },
            { key: 'result', label: 'Result', render: (row) => <StatusPill tone={row.result === 'pass' ? 'ok' : 'warn'}>{row.result}</StatusPill> },
          ]}
        />
      </Panel>
    </ConsolePage>
  )
}
