import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import ProtectedRoute from './components/ProtectedRoute'
import { AuthProvider } from './contexts/AuthContext'
import Login from './pages/Login'
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
import Notifications from './pages/Notifications'
import PipelineProfiles from './pages/PipelineProfiles'
import Quality from './pages/Quality'
import Access from './pages/Access'
import Operations from './pages/Operations'
import Understanding from './pages/Understanding'
import Conflicts from './pages/Conflicts'
import Plugins from './pages/Plugins'
import Evaluation from './pages/Evaluation'
import KnowledgeMap from './pages/KnowledgeMap'
import ProfileMatrix from './pages/ProfileMatrix'
import AnswerGen from './pages/AnswerGen'
import Wizard from './pages/Wizard'
import Conversations from './pages/Conversations'
import Usage from './pages/Usage'
import Backup from './pages/Backup'
import Team from './pages/Team'
import Sinks from './pages/Sinks'
import Stub from './pages/Stub'

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />

      <Route
        path="*"
        element={
          <ProtectedRoute>
            <Layout>
              <Routes>
                <Route path="/" element={<Overview />} />
                <Route path="/knowledge-bases" element={<KnowledgeBases />} />
                <Route path="/sources" element={<Sources />} />
                <Route path="/sinks" element={<Sinks />} />
                <Route path="/pipelines" element={<Pipelines />} />
                <Route path="/retrieval-lab" element={<RetrievalLab />} />
                <Route path="/pipeline-profiles" element={<PipelineProfiles />} />
                <Route path="/notifications" element={<Notifications />} />
                <Route path="/quality" element={<Quality />} />
                <Route path="/access" element={<Access />} />
                <Route path="/operations" element={<Operations />} />
                <Route path="/understanding" element={<Understanding />} />
                <Route path="/conflicts" element={<Conflicts />} />

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
                <Route path="/conversations" element={<Conversations />} />
                <Route path="/usage" element={<Usage />} />
                <Route path="/backup" element={<Backup />} />
                <Route path="/team" element={<Team />} />

                <Route path="*" element={<Stub title="Not Found" description="This page does not exist." />} />
              </Routes>
            </Layout>
          </ProtectedRoute>
        }
      />
    </Routes>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <AppRoutes />
    </AuthProvider>
  )
}
