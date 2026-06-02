import api from './api'

export interface AdminUser {
  id: string
  username: string
  email: string
  phone: string
  role: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface SystemConfig {
  key: string
  value: string
  description?: string
  updated_at?: string
}

export interface SharedDoc {
  id: string
  filename: string
  original_filename: string
  file_type: string
  doc_category: string
  is_shared: boolean
  user_id?: string
  created_at: string
}

// ==================== 用户管理 ====================

export const getAdminUsers = async (params?: {
  page?: number
  page_size?: number
  search?: string
  role?: string
}): Promise<{ users: AdminUser[]; total: number; page: number; page_size: number }> => {
  const { data } = await api.get('/admin/users', { params })
  return data
}

export const getAdminUser = async (userId: string): Promise<{ user: AdminUser; documents: SharedDoc[] }> => {
  const { data } = await api.get(`/admin/users/${userId}`)
  return data
}

export const updateAdminUser = async (
  userId: string,
  payload: {
    username?: string
    email?: string
    phone?: string
    password?: string
    is_active?: boolean
  }
): Promise<{ message: string; user: AdminUser }> => {
  const { data } = await api.put(`/admin/users/${userId}`, payload)
  return data
}

export const updateUserRole = async (userId: string, role: string): Promise<{ message: string }> => {
  const { data } = await api.put(`/admin/users/${userId}/role`, { role })
  return data
}

// ==================== 系统配置 ====================

export const getSystemConfigs = async (): Promise<SystemConfig[]> => {
  const { data } = await api.get('/admin/configs')
  return data
}

export const updateSystemConfigs = async (configs: Record<string, string>): Promise<{ message: string }> => {
  const { data } = await api.put('/admin/configs', { configs })
  return data
}

export const checkRegistrationEnabled = async (): Promise<boolean> => {
  try {
    const { data } = await api.get('/admin/configs/registration')
    return data.enabled
  } catch {
    return true
  }
}

// ==================== 共享文档 ====================

export const getSharedDocs = async (docCategory?: string): Promise<{ documents: SharedDoc[]; total: number }> => {
  const { data } = await api.get('/admin/shared-docs', {
    params: docCategory ? { doc_category: docCategory } : undefined,
  })
  return data
}

export const setDocShared = async (docId: string): Promise<{ message: string }> => {
  const { data } = await api.post(`/admin/shared-docs/${docId}`)
  return data
}

export const removeDocShared = async (docId: string): Promise<{ message: string }> => {
  const { data } = await api.delete(`/admin/shared-docs/${docId}`)
  return data
}

// ==================== 模型获取 ====================

export const fetchModels = async (apiKey: string, baseUrl: string): Promise<{ id: string; name: string }[]> => {
  const { data } = await api.post('/admin/configs/fetch-models', { api_key: apiKey, base_url: baseUrl })
  return data.models
}
