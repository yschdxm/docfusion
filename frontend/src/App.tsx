import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/layout/Layout'
import Dashboard from './pages/Dashboard'
import DocumentManager from './pages/DocumentManager'
import DocumentOperation from './pages/DocumentOperation'
import ExtractionModule from './pages/ExtractionModule'
import TableFillModule from './pages/TableFillModule'
import KnowledgeGraph from './pages/KnowledgeGraph'

function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="documents" element={<DocumentManager />} />
        <Route path="document-operation" element={<DocumentOperation />} />
        <Route path="extraction" element={<ExtractionModule />} />
        <Route path="table-fill" element={<TableFillModule />} />
        <Route path="knowledge" element={<KnowledgeGraph />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}

export default App
