import type { ConnectorSchema } from '../components/SchemaModal'

export const SOURCE_SCHEMAS: ConnectorSchema[] = [
  {
    id: 's3',
    label: 'S3 / MinIO / RustFS',
    description: 'S3-compatible object storage with explicit provider and credential refs.',
    fields: [
      { name: 'provider', label: 'Provider', type: 'select', required: true, options: [
        { value: 'aws-s3', label: 'AWS S3' },
        { value: 'minio', label: 'MinIO' },
        { value: 'rustfs', label: 'RustFS' },
        { value: 'custom-s3', label: 'Custom S3-compatible' },
      ] },
      { name: 'endpoint', label: 'Endpoint URL', type: 'url', required: true, placeholder: 'https://s3.example.com' },
      { name: 'bucket', label: 'Bucket', required: true, placeholder: 'kb-documents' },
      { name: 'prefix', label: 'Prefix', placeholder: 'policies/2026/' },
      { name: 'region', label: 'Region', placeholder: 'us-east-1' },
      { name: 'accessKeyRef', label: 'Access key ref', required: true, placeholder: 'env:S3_ACCESS_KEY_ID' },
      { name: 'secretKeyRef', label: 'Secret key ref', type: 'password', required: true, placeholder: 'env:S3_SECRET_ACCESS_KEY' },
      { name: 'schedule', label: 'Sync schedule', type: 'select', options: [
        { value: 'manual', label: 'Manual' },
        { value: 'hourly', label: 'Hourly' },
        { value: 'daily', label: 'Daily' },
      ] },
    ],
  },
  {
    id: 'web',
    label: 'Web crawler',
    description: 'Crawl public or authenticated web pages into a knowledge base.',
    fields: [
      { name: 'seedUrl', label: 'Seed URL', type: 'url', required: true, placeholder: 'https://docs.example.com' },
      { name: 'includePattern', label: 'Include pattern', placeholder: '/docs/**' },
      { name: 'authMode', label: 'Auth method', type: 'select', required: true, options: [
        { value: 'none', label: 'None' },
        { value: 'bearer', label: 'Bearer token' },
        { value: 'basic', label: 'Basic auth' },
      ] },
      { name: 'tokenRef', label: 'Token / password ref', type: 'password', placeholder: 'env:WEB_CRAWL_TOKEN' },
      { name: 'maxDepth', label: 'Max depth', type: 'number', placeholder: '3' },
      { name: 'schedule', label: 'Sync schedule', type: 'select', options: [
        { value: 'manual', label: 'Manual' },
        { value: 'daily', label: 'Daily' },
      ] },
    ],
  },
  {
    id: 'github',
    label: 'GitHub repository',
    description: 'Import markdown, source, issues, or docs from a repository.',
    fields: [
      { name: 'repo', label: 'Repository', required: true, placeholder: 'evilgaoshu/ragrig' },
      { name: 'branch', label: 'Branch', placeholder: 'main' },
      { name: 'paths', label: 'Paths', required: true, placeholder: 'docs/**, README.md' },
      { name: 'tokenRef', label: 'Token ref', type: 'password', placeholder: 'env:GITHUB_TOKEN' },
    ],
  },
]

export const SINK_SCHEMAS: ConnectorSchema[] = [
  {
    id: 'object-storage',
    label: 'Object storage export',
    description: 'Export chunks, metadata, or evaluation artifacts to S3/GCS/Azure/R2/B2.',
    fields: [
      { name: 'provider', label: 'Provider', type: 'select', required: true, options: [
        { value: 's3', label: 'AWS S3 / compatible' },
        { value: 'gcs', label: 'Google Cloud Storage' },
        { value: 'azure', label: 'Azure Blob' },
        { value: 'r2', label: 'Cloudflare R2' },
        { value: 'b2', label: 'Backblaze B2' },
      ] },
      { name: 'endpoint', label: 'Endpoint URL', type: 'url', placeholder: 'https://s3.example.com' },
      { name: 'bucket', label: 'Bucket / container', required: true, placeholder: 'rag-exports' },
      { name: 'prefix', label: 'Prefix', placeholder: 'prod/daily/' },
      { name: 'accessKeyRef', label: 'Access key ref', required: true, placeholder: 'env:EXPORT_ACCESS_KEY' },
      { name: 'secretKeyRef', label: 'Secret key ref', type: 'password', required: true, placeholder: 'env:EXPORT_SECRET_KEY' },
      { name: 'format', label: 'Payload format', type: 'select', required: true, options: [
        { value: 'ndjson', label: 'NDJSON' },
        { value: 'json', label: 'JSON array' },
        { value: 'parquet', label: 'Parquet' },
      ] },
      { name: 'retention', label: 'Retention', placeholder: '90d' },
    ],
  },
  {
    id: 'webhook',
    label: 'Webhook sink',
    description: 'POST chunk batches or pipeline events to an external system.',
    fields: [
      { name: 'endpoint', label: 'Endpoint URL', type: 'url', required: true, placeholder: 'https://agent.example.com/ingest' },
      { name: 'apiKeyRef', label: 'API key ref', type: 'password', placeholder: 'env:WEBHOOK_API_KEY' },
      { name: 'hmacRef', label: 'HMAC secret ref', type: 'password', placeholder: 'env:WEBHOOK_HMAC_SECRET' },
      { name: 'batchSize', label: 'Batch size', type: 'number', placeholder: '200' },
    ],
  },
]

export const PROVIDER_SCHEMAS: ConnectorSchema[] = [
  {
    id: 'openai',
    label: 'OpenAI-compatible',
    description: 'OpenAI, OpenRouter, vLLM, or any compatible chat/embedding endpoint.',
    fields: [
      { name: 'baseUrl', label: 'Base URL', type: 'url', required: true, placeholder: 'https://api.openai.com/v1' },
      { name: 'apiKeyRef', label: 'API key ref', type: 'password', required: true, placeholder: 'env:OPENAI_API_KEY' },
      { name: 'chatModel', label: 'Chat model', required: true, placeholder: 'gpt-4.1-mini' },
      { name: 'embeddingModel', label: 'Embedding model', placeholder: 'text-embedding-3-small' },
      { name: 'timeout', label: 'Timeout seconds', type: 'number', placeholder: '60' },
    ],
  },
  {
    id: 'voyage',
    label: 'Voyage embeddings',
    description: 'Dedicated embedding provider for retrieval quality experiments.',
    fields: [
      { name: 'apiKeyRef', label: 'API key ref', type: 'password', required: true, placeholder: 'env:VOYAGE_API_KEY' },
      { name: 'model', label: 'Model', required: true, placeholder: 'voyage-3-large' },
      { name: 'batchSize', label: 'Batch size', type: 'number', placeholder: '128' },
    ],
  },
  {
    id: 'ollama',
    label: 'Ollama local',
    description: 'Local model provider for air-gapped pilots and smoke tests.',
    fields: [
      { name: 'baseUrl', label: 'Base URL', type: 'url', required: true, placeholder: 'http://localhost:11434' },
      { name: 'chatModel', label: 'Chat model', required: true, placeholder: 'llama3.1' },
      { name: 'embeddingModel', label: 'Embedding model', placeholder: 'nomic-embed-text' },
    ],
  },
]

export const NOTIFICATION_ROUTE_SCHEMAS: ConnectorSchema[] = [
  {
    id: 'notification-route',
    label: 'Notification route',
    description: 'Route operational events to one or more delivery channels.',
    fields: [
      { name: 'event', label: 'Event type', type: 'select', required: true, options: [
        { value: 'pipeline_failed', label: 'Pipeline failed' },
        { value: 'budget_threshold', label: 'Budget threshold crossed' },
        { value: 'evaluation_regression', label: 'Evaluation regression' },
        { value: 'connector_auth_changed', label: 'Connector auth changed' },
      ] },
      { name: 'channels', label: 'Channels', required: true, placeholder: 'email, feishu, telegram' },
      { name: 'condition', label: 'Condition', required: true, placeholder: 'severity >= warn' },
      { name: 'severity', label: 'Severity', type: 'select', required: true, options: [
        { value: 'info', label: 'Info' },
        { value: 'warn', label: 'Warn' },
        { value: 'critical', label: 'Critical' },
      ] },
    ],
  },
]
