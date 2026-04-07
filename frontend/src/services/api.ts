import axios from 'axios'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 600000,  // 600秒，与后端 LLM 超时一致
  headers: {
    'Content-Type': 'application/json',
  },
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error('API Error:', error)
    return Promise.reject(error)
  }
)

export default api
