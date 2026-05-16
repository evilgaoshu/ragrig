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
import CostLatency from './pages/CostLatency'
import Models from './pages/Models'
import Plugins from './pages/Plugins'
import Evaluation from './pages/Evaluation'
import KnowledgeMap from './pages/KnowledgeMap'
import ProfileMatrix from './pages/ProfileMatrix'
import AnswerGen from './pages/AnswerGen'
import Settings from './pages/Settings'
import Wizard from './pages/Wizard'
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

        <Route path="/wizard" element={<Wizard />} />
        <Route path="/upload" element={<Upload />} />
        <Route path="/formats" element={<Formats />} />
        <Route path="/sanitizer-coverage" element={<SanitizerCoverage />} />
        <Route path="/sanitizer-drift" element={<SanitizerDrift />} />
        <Route path="/retrieval-benchmark" element={<RetrievalBenchmark />} />
        <Route path="/baseline-integrity" element={<BaselineIntegrity />} />
        <Route path="/answer-live-smoke" element={<AnswerLiveSmoke />} />
        <Route path="/parser-corpus" element={<ParserCorpus />} />
        <Route path="/ops-diagnostics" element={<OpsDiagnostics />} />
        <Route path="/cost-latency" element={<CostLatency />} />
        <Route path="/documents" element={<Documents />} />
        <Route path="/answer-gen" element={<AnswerGen />} />
        <Route path="/models" element={<Models />} />
        <Route path="/profile-matrix" element={<ProfileMatrix />} />
        <Route path="/plugins" element={<Plugins />} />
        <Route path="/evaluation" element={<Evaluation />} />
        <Route path="/knowledge-map" element={<KnowledgeMap />} />
        <Route path="/settings" element={<Settings />} />

        <Route path="*" element={<Stub title="Not Found" description="This page does not exist." />} />
      </Routes>
    </Layout>
  )
}
