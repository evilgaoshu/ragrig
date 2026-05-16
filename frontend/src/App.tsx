import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Overview from './pages/Overview'
import KnowledgeBases from './pages/KnowledgeBases'
import Sources from './pages/Sources'
import Pipelines from './pages/Pipelines'
import RetrievalLab from './pages/RetrievalLab'
import Upload from './pages/Upload'
import Formats from './pages/Formats'
import Documents from './pages/Documents'
import SanitizerCoverage from './pages/SanitizerCoverage'
import SanitizerDrift from './pages/SanitizerDrift'
import RetrievalBenchmark from './pages/RetrievalBenchmark'
import BaselineIntegrity from './pages/BaselineIntegrity'
import AnswerLiveSmoke from './pages/AnswerLiveSmoke'
import ParserCorpus from './pages/ParserCorpus'
import OpsDiagnostics from './pages/OpsDiagnostics'
import Models from './pages/Models'
import Plugins from './pages/Plugins'
import Evaluation from './pages/Evaluation'
import ProfileMatrix from './pages/ProfileMatrix'
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
        <Route path="/upload" element={<Upload />} />
        <Route path="/formats" element={<Formats />} />
        <Route path="/sanitizer-coverage" element={<SanitizerCoverage />} />
        <Route path="/sanitizer-drift" element={<SanitizerDrift />} />
        <Route path="/retrieval-benchmark" element={<RetrievalBenchmark />} />
        <Route path="/baseline-integrity" element={<BaselineIntegrity />} />
        <Route path="/answer-live-smoke" element={<AnswerLiveSmoke />} />
        <Route path="/parser-corpus" element={<ParserCorpus />} />
        <Route path="/ops-diagnostics" element={<OpsDiagnostics />} />
        <Route path="/documents" element={<Documents />} />
        <Route path="/answer-gen" element={<Stub title="Answer Gen" description="Grounded answer generation playground" />} />
        <Route path="/models" element={<Models />} />
        <Route path="/profile-matrix" element={<ProfileMatrix />} />
        <Route path="/plugins" element={<Plugins />} />
        <Route path="/evaluation" element={<Evaluation />} />
        <Route path="/settings" element={<Stub title="Settings" description="System settings and configuration" />} />

        <Route path="*" element={<Stub title="Not Found" description="This page does not exist." />} />
      </Routes>
    </Layout>
  )
}
