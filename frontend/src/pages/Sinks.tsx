import { useState } from 'react'
import {
  useKnowledgeBases,
  useAgentAccessExport,
  useWebhookExport,
  useCloudflareR2Export,
  useBackblazeB2Export,
  useAzureBlobExport,
  useGcsExport,
} from '../api/hooks'
import type { SinkExportResult, ObjectStorageExportResult } from '../api/hooks'
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
        {result.failed_batches > 0 && (
          <>
            <span className="text-red-600">Failed batches</span>
            <span className="font-mono font-bold text-red-600">{result.failed_batches}</span>
          </>
        )}
      </div>
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

// ── Object storage result panel ───────────────────────────────────────────────

function ObjectStorageResult({ result }: { result: ObjectStorageExportResult }) {
  return (
    <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 space-y-2">
      <div className="text-sm font-semibold text-emerald-800">
        {result.dry_run ? 'Dry run complete' : 'Export complete'}
      </div>
      <div className="grid grid-cols-2 gap-x-4 text-xs text-emerald-700">
        <span>Planned</span>
        <span className="font-mono font-bold">{result.planned_count}</span>
        <span>Uploaded</span>
        <span className="font-mono font-bold">{result.uploaded_count}</span>
        {result.skipped_count > 0 && (
          <>
            <span>Skipped</span>
            <span className="font-mono font-bold">{result.skipped_count}</span>
          </>
        )}
        {result.failed_count > 0 && (
          <>
            <span className="text-red-600">Failed</span>
            <span className="font-mono font-bold text-red-600">{result.failed_count}</span>
          </>
        )}
      </div>
      {result.artifact_keys.length > 0 && (
        <div className="text-xs text-emerald-600 pt-1">
          <div className="font-medium mb-1">Artifacts:</div>
          {result.artifact_keys.map((k) => (
            <div key={k} className="font-mono truncate">{k}</div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Cloudflare R2 sink ────────────────────────────────────────────────────────

function CloudflareR2Form({ kbs }: { kbs: { id: string; name: string }[] }) {
  const exportMut = useCloudflareR2Export()
  const [kbName, setKbName] = useState(kbs[0]?.name ?? '')
  const [accountId, setAccountId] = useState('')
  const [accessKeyId, setAccessKeyId] = useState('')
  const [secretAccessKey, setSecretAccessKey] = useState('')
  const [bucket, setBucket] = useState('')
  const [prefix, setPrefix] = useState('')
  const [jurisdiction, setJurisdiction] = useState('')
  const [dryRun, setDryRun] = useState(false)
  const [includeRetrieval, setIncludeRetrieval] = useState(true)
  const [includeMarkdown, setIncludeMarkdown] = useState(true)
  const [parquetExport, setParquetExport] = useState(false)
  const [result, setResult] = useState<ObjectStorageExportResult | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setResult(null)
    const res = await exportMut.mutateAsync({
      kbName,
      accountId,
      accessKeyId,
      secretAccessKey,
      bucket,
      prefix: prefix || undefined,
      jurisdiction: jurisdiction || undefined,
      dryRun,
      includeRetrievalArtifact: includeRetrieval,
      includeMarkdownSummary: includeMarkdown,
      parquetExport,
    })
    setResult(res)
  }

  const isValid = !!kbName && !!accountId && !!accessKeyId && !!secretAccessKey && !!bucket

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <SelectField
        label="Knowledge base"
        value={kbName}
        onChange={setKbName}
        options={kbs.map((k) => ({ value: k.name, label: k.name }))}
      />
      <TextField
        label="Account ID"
        value={accountId}
        onChange={setAccountId}
        placeholder="abc123..."
        hint="Cloudflare account ID from the R2 dashboard."
        required
      />
      <TextField
        label="Access Key ID"
        value={accessKeyId}
        onChange={setAccessKeyId}
        placeholder="R2 API token access key"
        required
      />
      <TextField
        label="Secret Access Key"
        value={secretAccessKey}
        onChange={setSecretAccessKey}
        placeholder="R2 API token secret"
        required
      />
      <TextField
        label="Bucket"
        value={bucket}
        onChange={setBucket}
        placeholder="my-ragrig-exports"
        required
      />

      <SectionDivider label="Options" />

      <TextField
        label="Prefix (optional)"
        value={prefix}
        onChange={setPrefix}
        placeholder="exports/"
      />
      <SelectField
        label="Jurisdiction"
        value={jurisdiction}
        onChange={setJurisdiction}
        options={[
          { value: '', label: 'Default (global)' },
          { value: 'eu', label: 'EU' },
          { value: 'fedramp', label: 'FedRAMP' },
        ]}
      />
      <CheckField label="Include retrieval JSON artifact" checked={includeRetrieval} onChange={setIncludeRetrieval} />
      <CheckField label="Include markdown summary" checked={includeMarkdown} onChange={setIncludeMarkdown} />
      <CheckField label="Export Parquet (requires pyarrow)" checked={parquetExport} onChange={setParquetExport} />
      <CheckField label="Dry run (plan only, do not upload)" checked={dryRun} onChange={setDryRun} />

      {exportMut.isError && (
        <ErrorBanner message={exportMut.error?.message ?? 'Export failed'} />
      )}

      {result && <ObjectStorageResult result={result} />}

      <div className="flex gap-3 pt-1">
        <Button type="submit" disabled={exportMut.isPending || !isValid}>
          {exportMut.isPending ? 'Exporting…' : dryRun ? 'Dry run' : 'Export to R2'}
        </Button>
        {result && (
          <Button
            type="button"
            variant="secondary"
            onClick={() => { setResult(null); exportMut.reset() }}
          >
            Reset
          </Button>
        )}
      </div>
    </form>
  )
}

// ── Backblaze B2 sink ─────────────────────────────────────────────────────────

function BackblazeB2Form({ kbs }: { kbs: { id: string; name: string }[] }) {
  const exportMut = useBackblazeB2Export()
  const [kbName, setKbName] = useState(kbs[0]?.name ?? '')
  const [region, setRegion] = useState('')
  const [keyId, setKeyId] = useState('')
  const [applicationKey, setApplicationKey] = useState('')
  const [bucket, setBucket] = useState('')
  const [prefix, setPrefix] = useState('')
  const [dryRun, setDryRun] = useState(false)
  const [includeRetrieval, setIncludeRetrieval] = useState(true)
  const [includeMarkdown, setIncludeMarkdown] = useState(true)
  const [parquetExport, setParquetExport] = useState(false)
  const [result, setResult] = useState<ObjectStorageExportResult | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setResult(null)
    const res = await exportMut.mutateAsync({
      kbName,
      region,
      keyId,
      applicationKey,
      bucket,
      prefix: prefix || undefined,
      dryRun,
      includeRetrievalArtifact: includeRetrieval,
      includeMarkdownSummary: includeMarkdown,
      parquetExport,
    })
    setResult(res)
  }

  const isValid = !!kbName && !!region && !!keyId && !!applicationKey && !!bucket

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <SelectField
        label="Knowledge base"
        value={kbName}
        onChange={setKbName}
        options={kbs.map((k) => ({ value: k.name, label: k.name }))}
      />
      <TextField
        label="Region"
        value={region}
        onChange={setRegion}
        placeholder="us-west-004"
        hint="B2 region code (e.g. us-west-004, eu-central-003)."
        required
      />
      <TextField
        label="Application Key ID"
        value={keyId}
        onChange={setKeyId}
        placeholder="B2 application key ID"
        required
      />
      <TextField
        label="Application Key"
        value={applicationKey}
        onChange={setApplicationKey}
        placeholder="B2 application key (secret)"
        required
      />
      <TextField
        label="Bucket"
        value={bucket}
        onChange={setBucket}
        placeholder="my-b2-bucket"
        required
      />

      <SectionDivider label="Options" />

      <TextField
        label="Prefix (optional)"
        value={prefix}
        onChange={setPrefix}
        placeholder="exports/"
      />
      <CheckField label="Include retrieval JSON artifact" checked={includeRetrieval} onChange={setIncludeRetrieval} />
      <CheckField label="Include markdown summary" checked={includeMarkdown} onChange={setIncludeMarkdown} />
      <CheckField label="Export Parquet (requires pyarrow)" checked={parquetExport} onChange={setParquetExport} />
      <CheckField label="Dry run (plan only, do not upload)" checked={dryRun} onChange={setDryRun} />

      {exportMut.isError && (
        <ErrorBanner message={exportMut.error?.message ?? 'Export failed'} />
      )}

      {result && <ObjectStorageResult result={result} />}

      <div className="flex gap-3 pt-1">
        <Button type="submit" disabled={exportMut.isPending || !isValid}>
          {exportMut.isPending ? 'Exporting…' : dryRun ? 'Dry run' : 'Export to B2'}
        </Button>
        {result && (
          <Button
            type="button"
            variant="secondary"
            onClick={() => { setResult(null); exportMut.reset() }}
          >
            Reset
          </Button>
        )}
      </div>
    </form>
  )
}

// ── Azure Blob sink ───────────────────────────────────────────────────────────

function AzureBlobForm({ kbs }: { kbs: { id: string; name: string }[] }) {
  const exportMut = useAzureBlobExport()
  const [kbName, setKbName] = useState(kbs[0]?.name ?? '')
  const [accountName, setAccountName] = useState('')
  const [accountKey, setAccountKey] = useState('')
  const [container, setContainer] = useState('')
  const [prefix, setPrefix] = useState('')
  const [dryRun, setDryRun] = useState(false)
  const [includeRetrieval, setIncludeRetrieval] = useState(true)
  const [includeMarkdown, setIncludeMarkdown] = useState(true)
  const [parquetExport, setParquetExport] = useState(false)
  const [result, setResult] = useState<ObjectStorageExportResult | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setResult(null)
    const res = await exportMut.mutateAsync({
      kbName,
      accountName,
      accountKey,
      container,
      prefix: prefix || undefined,
      dryRun,
      includeRetrievalArtifact: includeRetrieval,
      includeMarkdownSummary: includeMarkdown,
      parquetExport,
    })
    setResult(res)
  }

  const isValid = !!kbName && !!accountName && !!accountKey && !!container

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <SelectField
        label="Knowledge base"
        value={kbName}
        onChange={setKbName}
        options={kbs.map((k) => ({ value: k.name, label: k.name }))}
      />
      <TextField
        label="Storage Account Name"
        value={accountName}
        onChange={setAccountName}
        placeholder="mystorageaccount"
        required
      />
      <TextField
        label="Account Key"
        value={accountKey}
        onChange={setAccountKey}
        placeholder="Azure storage account key (secret)"
        required
      />
      <TextField
        label="Container"
        value={container}
        onChange={setContainer}
        placeholder="my-exports-container"
        required
      />

      <SectionDivider label="Options" />

      <TextField
        label="Prefix (optional)"
        value={prefix}
        onChange={setPrefix}
        placeholder="exports/"
      />
      <CheckField label="Include retrieval JSON artifact" checked={includeRetrieval} onChange={setIncludeRetrieval} />
      <CheckField label="Include markdown summary" checked={includeMarkdown} onChange={setIncludeMarkdown} />
      <CheckField label="Export Parquet (requires pyarrow)" checked={parquetExport} onChange={setParquetExport} />
      <CheckField label="Dry run (plan only, do not upload)" checked={dryRun} onChange={setDryRun} />

      {exportMut.isError && (
        <ErrorBanner message={exportMut.error?.message ?? 'Export failed'} />
      )}

      {result && <ObjectStorageResult result={result} />}

      <div className="flex gap-3 pt-1">
        <Button type="submit" disabled={exportMut.isPending || !isValid}>
          {exportMut.isPending ? 'Exporting…' : dryRun ? 'Dry run' : 'Export to Azure Blob'}
        </Button>
        {result && (
          <Button
            type="button"
            variant="secondary"
            onClick={() => { setResult(null); exportMut.reset() }}
          >
            Reset
          </Button>
        )}
      </div>
    </form>
  )
}

// ── GCS sink ──────────────────────────────────────────────────────────────────

function GcsForm({ kbs }: { kbs: { id: string; name: string }[] }) {
  const exportMut = useGcsExport()
  const [kbName, setKbName] = useState(kbs[0]?.name ?? '')
  const [accessKey, setAccessKey] = useState('')
  const [secretKey, setSecretKey] = useState('')
  const [bucket, setBucket] = useState('')
  const [prefix, setPrefix] = useState('')
  const [dryRun, setDryRun] = useState(false)
  const [includeRetrieval, setIncludeRetrieval] = useState(true)
  const [includeMarkdown, setIncludeMarkdown] = useState(true)
  const [parquetExport, setParquetExport] = useState(false)
  const [result, setResult] = useState<ObjectStorageExportResult | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setResult(null)
    const res = await exportMut.mutateAsync({
      kbName,
      accessKey,
      secretKey,
      bucket,
      prefix: prefix || undefined,
      dryRun,
      includeRetrievalArtifact: includeRetrieval,
      includeMarkdownSummary: includeMarkdown,
      parquetExport,
    })
    setResult(res)
  }

  const isValid = !!kbName && !!accessKey && !!secretKey && !!bucket

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <SelectField
        label="Knowledge base"
        value={kbName}
        onChange={setKbName}
        options={kbs.map((k) => ({ value: k.name, label: k.name }))}
      />
      <TextField
        label="HMAC Access Key"
        value={accessKey}
        onChange={setAccessKey}
        placeholder="GCS HMAC access key"
        required
      />
      <TextField
        label="HMAC Secret Key"
        value={secretKey}
        onChange={setSecretKey}
        placeholder="GCS HMAC secret key"
        required
      />
      <TextField
        label="Bucket"
        value={bucket}
        onChange={setBucket}
        placeholder="my-gcs-exports"
        required
      />

      <SectionDivider label="Options" />

      <TextField
        label="Prefix (optional)"
        value={prefix}
        onChange={setPrefix}
        placeholder="exports/"
      />
      <CheckField label="Include retrieval JSON artifact" checked={includeRetrieval} onChange={setIncludeRetrieval} />
      <CheckField label="Include markdown summary" checked={includeMarkdown} onChange={setIncludeMarkdown} />
      <CheckField label="Export Parquet (requires pyarrow)" checked={parquetExport} onChange={setParquetExport} />
      <CheckField label="Dry run (plan only, do not upload)" checked={dryRun} onChange={setDryRun} />

      {exportMut.isError && (
        <ErrorBanner message={exportMut.error?.message ?? 'Export failed'} />
      )}

      {result && <ObjectStorageResult result={result} />}

      <div className="flex gap-3 pt-1">
        <Button type="submit" disabled={exportMut.isPending || !isValid}>
          {exportMut.isPending ? 'Exporting…' : dryRun ? 'Dry run' : 'Export to GCS'}
        </Button>
        {result && (
          <Button
            type="button"
            variant="secondary"
            onClick={() => { setResult(null); exportMut.reset() }}
          >
            Reset
          </Button>
        )}
      </div>
    </form>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

type SinkTab = 'agent_access' | 'webhook' | 'cloudflare_r2' | 'backblaze_b2' | 'azure_blob' | 'gcs'

export default function Sinks() {
  const { data: kbs, isLoading } = useKnowledgeBases()
  const [tab, setTab] = useState<SinkTab>('agent_access')

  const kbList = (kbs ?? []).map((kb) => ({ id: String(kb.id), name: kb.name }))

  const TABS: { id: SinkTab; label: string }[] = [
    { id: 'agent_access', label: 'Agent Access (MCP)' },
    { id: 'webhook', label: 'Webhook' },
    { id: 'cloudflare_r2', label: 'Cloudflare R2' },
    { id: 'backblaze_b2', label: 'Backblaze B2' },
    { id: 'azure_blob', label: 'Azure Blob' },
    { id: 'gcs', label: 'Google Cloud Storage' },
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
            {tab === 'cloudflare_r2' && <CloudflareR2Form kbs={kbList} />}
            {tab === 'backblaze_b2' && <BackblazeB2Form kbs={kbList} />}
            {tab === 'azure_blob' && <AzureBlobForm kbs={kbList} />}
            {tab === 'gcs' && <GcsForm kbs={kbList} />}
          </div>
        </div>
      )}
    </div>
  )
}
