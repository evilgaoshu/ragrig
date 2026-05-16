import { Link } from 'react-router-dom'
import { useSystemStatus, useKnowledgeBases, useDocuments } from '../api/hooks'

type Step = {
  num: number
  label: string
  description: string
  cta: string
  href: string
  done?: boolean
  warn?: boolean
}

function StepCard({ step }: { step: Step }) {
  const border = step.done
    ? 'border-emerald-200 bg-emerald-50'
    : step.warn
      ? 'border-amber-200 bg-amber-50'
      : 'border-gray-200 bg-white'

  return (
    <div className={`border rounded-lg px-4 py-4 ${border}`}>
      <div className="flex items-start gap-3">
        <div className={`shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold ${
          step.done ? 'bg-emerald-500 text-white' : 'bg-gray-200 text-gray-600'
        }`}>
          {step.done ? '✓' : step.num}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-gray-800">{step.label}</div>
          <div className="text-xs text-gray-500 mt-0.5">{step.description}</div>
        </div>
        <Link
          to={step.href}
          className="shrink-0 text-xs font-medium text-brand hover:underline whitespace-nowrap"
        >
          {step.cta} →
        </Link>
      </div>
    </div>
  )
}

export default function Wizard() {
  const { data: status } = useSystemStatus()
  const { data: kbs } = useKnowledgeBases()
  const { data: docs } = useDocuments()

  const systemOk = status?.api === 'ok' && status?.database === 'connected' && status?.vector === 'ok'
  const hasKB = (kbs?.length ?? 0) > 0
  const hasDocs = (docs?.length ?? 0) > 0

  const steps: Step[] = [
    {
      num: 1,
      label: 'Verify system health',
      description: 'Check that the API, database, and vector backend are all healthy.',
      cta: 'Overview',
      href: '/',
      done: systemOk,
      warn: !systemOk,
    },
    {
      num: 2,
      label: 'Create a knowledge base',
      description: 'A knowledge base groups documents and their embeddings by topic or team.',
      cta: 'Knowledge Bases',
      href: '/knowledge-bases',
      done: hasKB,
    },
    {
      num: 3,
      label: 'Ingest documents',
      description: 'Upload files directly, or connect an S3 / fileshare source.',
      cta: 'Upload',
      href: '/upload',
      done: hasDocs,
    },
    {
      num: 4,
      label: 'Verify ingestion',
      description: 'Check pipeline runs completed and documents are indexed with chunks.',
      cta: 'Pipelines',
      href: '/pipelines',
      done: hasDocs,
    },
    {
      num: 5,
      label: 'Test retrieval',
      description: 'Run a semantic search to confirm embeddings and retrieval quality.',
      cta: 'Retrieval Lab',
      href: '/retrieval-lab',
    },
    {
      num: 6,
      label: 'Generate a grounded answer',
      description: 'Combine retrieval with an LLM to produce cited answers from your documents.',
      cta: 'Answer Gen',
      href: '/answer-gen',
    },
  ]

  const doneCount = steps.filter((s) => s.done).length

  return (
    <div className="p-6 space-y-6 max-w-xl">
      <div>
        <h1 className="text-lg font-bold text-gray-900">Setup Wizard</h1>
        <p className="text-gray-500 text-sm mt-0.5">Guided ingestion setup — {doneCount} of {steps.length} steps done</p>
      </div>

      {/* Progress bar */}
      <div className="bg-gray-100 rounded-full h-1.5 overflow-hidden">
        <div
          className="bg-brand h-full rounded-full transition-all duration-500"
          style={{ width: `${(doneCount / steps.length) * 100}%` }}
        />
      </div>

      <div className="space-y-3">
        {steps.map((step) => (
          <StepCard key={step.num} step={step} />
        ))}
      </div>
    </div>
  )
}
