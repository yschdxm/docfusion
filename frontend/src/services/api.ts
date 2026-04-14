import axios from 'axios'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 600000,
  headers: {
    'Content-Type': 'application/json',
  },
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('docfusion_auth_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      localStorage.removeItem('docfusion_auth_user')
      localStorage.removeItem('docfusion_auth_token')
      window.dispatchEvent(new Event('docfusion-auth-user-changed'))
    }
    console.error('API Error:', error)
    return Promise.reject(error)
  }
)

export default api
