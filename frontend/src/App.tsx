import { Navigate, Route, Routes } from 'react-router-dom'
import { useEffect } from 'react'
import Layout from './components/layout/Layout'
import Dashboard from './pages/Dashboard'
import DocumentWorkspace from './pages/DocumentWorkspace'
import KnowledgeGraph from './pages/KnowledgeGraph'
import WorkLog from './pages/WorkLog'
import ProfileCenter from './pages/ProfileCenter'
import AdminCenter from './pages/AdminCenter'
import Login from './pages/Login'
import Register from './pages/Register'
import { fetchCurrentUser, isAuthenticated, logout, isAdmin } from './services/auth'

function RequireAuth({ children }: { children: JSX.Element }) {
  if (!isAuthenticated()) {
    return <Navigate to="/login" replace />
  }
  return children
}

function RequireAdmin({ children }: { children: JSX.Element }) {
  if (!isAuthenticated()) {
    return <Navigate to="/login" replace />
  }
  if (!isAdmin()) {
    return <Navigate to="/" replace />
  }
  return children
}

function PublicOnly({ children }: { children: JSX.Element }) {
  if (isAuthenticated()) {
    return <Navigate to="/" replace />
  }
  return children
}

function App() {
  useEffect(() => {
    if (!isAuthenticated()) return

    fetchCurrentUser().catch(() => {
      logout()
    })
  }, [])

  return (
    <Routes>
      <Route
        path="/login"
        element={
          <PublicOnly>
            <Login />
          </PublicOnly>
        }
      />
      <Route
        path="/register"
        element={
          <PublicOnly>
            <Register />
          </PublicOnly>
        }
      />

      <Route
        path="/"
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="documents" element={<DocumentWorkspace />} />
        <Route path="knowledge" element={<KnowledgeGraph />} />
        <Route path="work-log" element={<WorkLog />} />
        <Route path="profile" element={<ProfileCenter />} />
        <Route
          path="admin"
          element={
            <RequireAdmin>
              <AdminCenter />
            </RequireAdmin>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}

export default App
