import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { Toaster } from 'react-hot-toast'
import App from './App'
import './styles/globals.css'
import { initTheme } from './services/theme'

initTheme()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
      <Toaster
        position="top-center"
        toastOptions={{
          className: 'toast-glass',
          duration: 3000,
        }}
        containerStyle={{ top: 60 }}
      />
    </BrowserRouter>
  </React.StrictMode>,
)
