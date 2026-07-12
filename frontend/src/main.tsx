import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'react-hot-toast'
import App from './App'
import './styles/globals.css'
import { initTheme } from './services/theme'

initTheme()

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
        <Toaster
          position="top-center"
          toastOptions={{
            className: 'glass-dark',
            duration: 3000,
            style: {
              background: 'var(--theme-glass-bg)',
              color: 'var(--theme-body-text)',
              border: '1px solid var(--theme-border)',
              boxShadow: '0 10px 30px rgba(15, 23, 42, 0.08)',
            },
            success: {
              iconTheme: {
                primary: 'var(--theme-primary)',
                secondary: '#ffffff',
              },
            },
            error: {
              iconTheme: {
                primary: '#ef4444',
                secondary: '#ffffff',
              },
            },
          }}
          containerStyle={{ top: 60 }}
        />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
)
