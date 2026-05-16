import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Overview from './pages/Overview'
import KnowledgeBases from './pages/KnowledgeBases'
import Sources from './pages/Sources'
import Pipelines from './pages/Pipelines'
import RetrievalLab from './pages/RetrievalLab'
import Stub from './pages/Stub'

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Overview />} />
        <Route path="/knowledge-bases" element={<KnowledgeBases />} />
        <Route path="/sources" element={<Sources />} />
        <Route path="/pipelines" element={<Pipelines />} />
        <Route path="/retrieval-lab" element={<RetrievalLab />} />

        <Route path="/wizard" element={<Stub title="Setup Wizard" description="Guided ingestion setup" />} />
        <Route path="/upload" element={<Stub title="Upload" description="Direct file upload to a knowledge base" />} />
        <Route path="/formats" element={<Stub title="Formats" description="Supported file format registry" />} />
        <Route path="/sanitizer-coverage" element={<Stub title="Sanitizer Coverage" description="Parser redaction coverage metrics" />} />
        <Route path="/sanitizer-drift" element={<Stub title="Sanitizer Drift" description="Sanitizer drift history and trend" />} />
        <Route path="/retrieval-benchmark" element={<Stub title="Retrieval Benchmark" description="Retrieval quality benchmark results" />} />
        <Route path="/baseline-integrity" element={<Stub title="Baseline Integrity" description="Retrieval baseline health check" />} />
        <Route path="/answer-live-smoke" element={<Stub title="Answer Live Smoke" description="LLM answer pipeline health" />} />
        <Route path="/parser-corpus" element={<Stub title="Parser Corpus" description="Advanced parser corpus status" />} />
        <Route path="/ops-diagnostics" element={<Stub title="Ops Diagnostics" description="Deploy, backup, and restore diagnostics" />} />
        <Route path="/documents" element={<Stub title="Documents" description="Document version browser" />} />
        <Route path="/answer-gen" element={<Stub title="Answer Gen" description="Grounded answer generation playground" />} />
        <Route path="/models" element={<Stub title="Models" description="Embedding models and rerankers" />} />
        <Route path="/profile-matrix" element={<Stub title="Profile Matrix" description="Processing profile override matrix" />} />
        <Route path="/plugins" element={<Stub title="Plugins" description="Source plugin registry and wizard" />} />
        <Route path="/evaluation" element={<Stub title="Evaluation" description="RAG evaluation runs and baselines" />} />
        <Route path="/settings" element={<Stub title="Settings" description="System settings and configuration" />} />

        <Route path="*" element={<Stub title="Not Found" description="This page does not exist." />} />
      </Routes>
    </Layout>
  )
}
