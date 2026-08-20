import { Navigate, Route, Routes } from 'react-router-dom'
import { Suspense, lazy, useEffect } from 'react'
import Layout from './components/layout/Layout'
import { fetchCurrentUser, isAuthenticated, logout, isAdmin } from './services/auth'

// 按路由懒加载，首屏只下载当前页代码（知识图谱页含 vis-network 等大依赖）
const Dashboard = lazy(() => import('./pages/Dashboard'))
const DocumentManager = lazy(() => import('./pages/DocumentManager'))
const DocumentOperation = lazy(() => import('./pages/DocumentOperation'))
const KnowledgeGraph = lazy(() => import('./pages/KnowledgeGraph'))
const WorkLog = lazy(() => import('./pages/WorkLog'))
const EmailManagement = lazy(() => import('./pages/EmailManagement'))
const ProfileCenter = lazy(() => import('./pages/ProfileCenter'))
const AdminCenter = lazy(() => import('./pages/AdminCenter'))
const Login = lazy(() => import('./pages/Login'))
const Register = lazy(() => import('./pages/Register'))

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
    <Suspense fallback={<div className="flex h-screen h-dvh items-center justify-center text-gray-400">加载中…</div>}>
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
        <Route path="documents" element={<DocumentManager />} />
        <Route path="document-operation" element={<DocumentOperation />} />
        <Route path="knowledge" element={<KnowledgeGraph />} />
        <Route path="work-log" element={<WorkLog />} />
        <Route path="email-management" element={<EmailManagement />} />
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
    </Suspense>
  )
}

export default App
