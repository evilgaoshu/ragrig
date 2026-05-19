import { useState } from 'react'
import { useKnowledgeBases, useAgentAccessExport, useWebhookExport } from '../api/hooks'
import type { SinkExportResult } from '../api/hooks'
import {
  Button,
  TextField,
  SelectField,
  CheckField,
  SectionDivider,
  ErrorBanner,
} from '../components/ui'

// ── Result panel ──────────────────────────────────────────────────────────────

function ExportResult({ result }: { result: SinkExportResult }) {
  return (
    <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 space-y-2">
      <div className="text-sm font-semibold text-emerald-800">
        {result.dry_run ? 'Dry run complete' : 'Export complete'}
      </div>
      <div className="grid grid-cols-2 gap-x-4 text-xs text-emerald-700">
        <span>Total chunks</span>
        <span className="font-mono font-bold">{result.total_chunks}</span>
        <span>Batches sent</span>
        <span className="font-mono font-bold">{result.batches_sent}</span>
      </div>
      {result.errors.length > 0 && (
        <div className="mt-2 space-y-1">
          {result.errors.map((e, i) => (
            <div key={i} className="text-xs text-red-600 bg-red-50 rounded px-2 py-1">
              {e}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Agent Access sink ─────────────────────────────────────────────────────────

function AgentAccessForm({ kbs }: { kbs: { id: string; name: string }[] }) {
  const exportMut = useAgentAccessExport()
  const [kbName, setKbName] = useState(kbs[0]?.name ?? '')
  const [endpointUrl, setEndpointUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [hmacSecret, setHmacSecret] = useState('')
  const [batchSize, setBatchSize] = useState('100')
  const [dryRun, setDryRun] = useState(false)
  const [result, setResult] = useState<SinkExportResult | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setResult(null)
    const res = await exportMut.mutateAsync({
      kbName,
      endpointUrl,
      apiKey,
      hmacSecret: hmacSecret || undefined,
      batchSize: parseInt(batchSize, 10) || 100,
      dryRun,
    })
    setResult(res)
  }

  const isValid = !!kbName && !!endpointUrl && !!apiKey

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <SelectField
        label="Knowledge base"
        value={kbName}
        onChange={setKbName}
        options={kbs.map((k) => ({ value: k.name, label: k.name }))}
      />
      <TextField
        label="Endpoint URL"
        value={endpointUrl}
        onChange={setEndpointUrl}
        placeholder="https://your-agent.example.com/api/ingest"
        hint="MCP endpoint or any HTTP endpoint that accepts batched chunk payloads."
        required
      />
      <TextField
        label="API key (Bearer token)"
        value={apiKey}
        onChange={setApiKey}
        placeholder="my-secret-key or env:AGENT_API_KEY"
        hint="Sent as Authorization: Bearer <key>. Use env:VAR to reference a server env var."
        required
      />

      <SectionDivider label="Options" />

      <TextField
        label="HMAC secret (optional)"
        value={hmacSecret}
        onChange={setHmacSecret}
        placeholder="env:AGENT_HMAC_SECRET"
        hint="Signs each request with X-Signature-256: sha256=<hex>. Prefer env:VAR."
      />
      <TextField
        label="Batch size"
        value={batchSize}
        onChange={setBatchSize}
        type="number"
        hint="Chunks per POST request."
      />
      <CheckField label="Dry run (collect chunks but do not send)" checked={dryRun} onChange={setDryRun} />

      {exportMut.isError && (
        <ErrorBanner message={exportMut.error?.message ?? 'Export failed'} />
      )}

      {result && <ExportResult result={result} />}

      <div className="flex gap-3 pt-1">
        <Button type="submit" disabled={exportMut.isPending || !isValid}>
          {exportMut.isPending ? 'Exporting…' : dryRun ? 'Dry run' : 'Export'}
        </Button>
        {result && (
          <Button
            type="button"
            variant="secondary"
            onClick={() => {
              setResult(null)
              exportMut.reset()
            }}
          >
            Reset
          </Button>
        )}
      </div>
    </form>
  )
}

// ── Webhook sink ──────────────────────────────────────────────────────────────

function WebhookForm({ kbs }: { kbs: { id: string; name: string }[] }) {
  const exportMut = useWebhookExport()
  const [kbName, setKbName] = useState(kbs[0]?.name ?? '')
  const [endpointUrl, setEndpointUrl] = useState('')
  const [hmacSecret, setHmacSecret] = useState('')
  const [format, setFormat] = useState('ndjson')
  const [batchSize, setBatchSize] = useState('200')
  const [dryRun, setDryRun] = useState(false)
  const [result, setResult] = useState<SinkExportResult | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setResult(null)
    const res = await exportMut.mutateAsync({
      kbName,
      endpointUrl,
      hmacSecret: hmacSecret || undefined,
      format,
      batchSize: parseInt(batchSize, 10) || 200,
      dryRun,
    })
    setResult(res)
  }

  const isValid = !!kbName && !!endpointUrl

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <SelectField
        label="Knowledge base"
        value={kbName}
        onChange={setKbName}
        options={kbs.map((k) => ({ value: k.name, label: k.name }))}
      />
      <TextField
        label="Endpoint URL"
        value={endpointUrl}
        onChange={setEndpointUrl}
        placeholder="https://your-service.example.com/webhook/chunks"
        hint="Receives NDJSON or JSON array batches via HTTP POST."
        required
      />

      <SectionDivider label="Options" />

      <SelectField
        label="Payload format"
        value={format}
        onChange={setFormat}
        options={[
          { value: 'ndjson', label: 'NDJSON (one JSON object per line)' },
          { value: 'json', label: 'JSON array' },
        ]}
      />
      <TextField
        label="HMAC secret (optional)"
        value={hmacSecret}
        onChange={setHmacSecret}
        placeholder="env:WEBHOOK_HMAC_SECRET"
        hint="Signs each request with X-Signature-256: sha256=<hex>. Prefer env:VAR."
      />
      <TextField
        label="Batch size"
        value={batchSize}
        onChange={setBatchSize}
        type="number"
        hint="Chunks per POST request."
      />
      <CheckField label="Dry run (collect chunks but do not send)" checked={dryRun} onChange={setDryRun} />

      {exportMut.isError && (
        <ErrorBanner message={exportMut.error?.message ?? 'Export failed'} />
      )}

      {result && <ExportResult result={result} />}

      <div className="flex gap-3 pt-1">
        <Button type="submit" disabled={exportMut.isPending || !isValid}>
          {exportMut.isPending ? 'Exporting…' : dryRun ? 'Dry run' : 'Export'}
        </Button>
        {result && (
          <Button
            type="button"
            variant="secondary"
            onClick={() => {
              setResult(null)
              exportMut.reset()
            }}
          >
            Reset
          </Button>
        )}
      </div>
    </form>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

type SinkTab = 'agent_access' | 'webhook'

export default function Sinks() {
  const { data: kbs, isLoading } = useKnowledgeBases()
  const [tab, setTab] = useState<SinkTab>('agent_access')

  const kbList = (kbs ?? []).map((kb) => ({ id: String(kb.id), name: kb.name }))

  const TABS: { id: SinkTab; label: string }[] = [
    { id: 'agent_access', label: 'Agent Access (MCP)' },
    { id: 'webhook', label: 'Webhook' },
  ]

  return (
    <div className="p-6 space-y-6 max-w-2xl">
      <div>
        <h1 className="text-lg font-bold text-gray-900">Sinks</h1>
        <p className="text-gray-500 text-sm mt-0.5">
          Export knowledge base chunks to external endpoints
        </p>
      </div>

      {isLoading && <div className="text-sm text-gray-400">Loading knowledge bases…</div>}

      {!isLoading && kbList.length === 0 && (
        <div className="text-sm text-gray-500">
          No knowledge bases found. Create one first.
        </div>
      )}

      {!isLoading && kbList.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          {/* Tab bar */}
          <div className="flex border-b border-gray-200">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`px-5 py-3 text-sm font-medium transition-colors ${
                  tab === t.id
                    ? 'border-b-2 border-brand text-brand'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          <div className="p-6">
            {tab === 'agent_access' && <AgentAccessForm kbs={kbList} />}
            {tab === 'webhook' && <WebhookForm kbs={kbList} />}
          </div>
        </div>
      )}
    </div>
  )
}
