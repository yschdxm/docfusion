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
    // FastAPI 422 的 detail 是对象数组 [{type, loc, msg, ...}]，
    // 直接交给 toast/UI 渲染会触发 React error #31（对象不是合法的 React 子节点）白屏，
    // 在这里统一拍平为字符串，所有 error.response?.data?.detail 调用点自动受益
    const detail = error?.response?.data?.detail
    if (Array.isArray(detail)) {
      error.response.data.detail = detail
        .map((d: { loc?: unknown[]; msg?: string }) => {
          const loc = Array.isArray(d?.loc) ? d.loc.filter((p) => p !== 'body').join('.') : ''
          return loc ? `${loc}: ${d?.msg ?? ''}` : (d?.msg ?? JSON.stringify(d))
        })
        .join('；')
    }
    console.error('API Error:', error)
    return Promise.reject(error)
  }
)

export default api
