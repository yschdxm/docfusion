import api from './api'

export interface AuthUser {
  id: string
  username: string
  email: string
  phone: string
  is_active: boolean
  role: 'user' | 'admin' | 'super_admin'
  selected_model?: string
  created_at: string
  updated_at: string
}

interface AuthPayload {
  access_token: string
  token_type: string
  user: AuthUser
}

const AUTH_USER_KEY = 'docfusion_auth_user'
const AUTH_TOKEN_KEY = 'docfusion_auth_token'
const AUTH_LAST_LOGIN_AT_KEY = 'docfusion_last_login_at'
export const AUTH_USER_CHANGED_EVENT = 'docfusion-auth-user-changed'

const persistAuthState = (payload: AuthPayload, markLogin: boolean) => {
  localStorage.setItem(AUTH_USER_KEY, JSON.stringify(payload.user))
  localStorage.setItem(AUTH_TOKEN_KEY, payload.access_token)
  if (markLogin) {
    localStorage.setItem(AUTH_LAST_LOGIN_AT_KEY, new Date().toISOString())
  }
  window.dispatchEvent(new Event(AUTH_USER_CHANGED_EVENT))
}

export const getAuthUser = (): AuthUser | null => {
  const raw = localStorage.getItem(AUTH_USER_KEY)
  if (!raw) return null

  try {
    return JSON.parse(raw) as AuthUser
  } catch {
    return null
  }
}

export const getAuthToken = (): string | null => localStorage.getItem(AUTH_TOKEN_KEY)

export const getLastLoginAt = (): string | null => localStorage.getItem(AUTH_LAST_LOGIN_AT_KEY)

export const setAuthUserField = (updates: Partial<AuthUser>) => {
  const user = getAuthUser()
  if (!user) return
  const updated = { ...user, ...updates }
  localStorage.setItem(AUTH_USER_KEY, JSON.stringify(updated))
  window.dispatchEvent(new Event(AUTH_USER_CHANGED_EVENT))
}

export const isAuthenticated = (): boolean => Boolean(getAuthToken() && getAuthUser())

export const loginWithPassword = async (account: string, password: string): Promise<AuthUser> => {
  const { data } = await api.post<AuthPayload>('/auth/login', {
    account: account.trim(),
    password,
  })
  persistAuthState(data, true)
  return data.user
}

export const registerWithPassword = async (
  username: string,
  email: string,
  phone: string,
  password: string
): Promise<AuthUser> => {
  const { data } = await api.post<AuthPayload>('/auth/register', {
    username: username.trim(),
    email: email.trim().toLowerCase(),
    phone: phone.trim(),
    password,
  })
  persistAuthState(data, true)
  return data.user
}

export const fetchCurrentUser = async (): Promise<AuthUser> => {
  const { data } = await api.get<AuthUser>('/auth/me')
  localStorage.setItem(AUTH_USER_KEY, JSON.stringify(data))
  window.dispatchEvent(new Event(AUTH_USER_CHANGED_EVENT))
  return data
}

export const updateAuthUser = async (
  patch: Pick<AuthUser, 'username' | 'email' | 'phone'>
): Promise<AuthUser> => {
  const { data } = await api.put<AuthUser>('/auth/me', {
    username: patch.username.trim(),
    email: patch.email.trim().toLowerCase(),
    phone: patch.phone.trim(),
  })
  localStorage.setItem(AUTH_USER_KEY, JSON.stringify(data))
  window.dispatchEvent(new Event(AUTH_USER_CHANGED_EVENT))
  return data
}

export const changePassword = async (currentPassword: string, newPassword: string) => {
  await api.post('/auth/change-password', {
    current_password: currentPassword,
    new_password: newPassword,
  })
}

export const logout = () => {
  localStorage.removeItem(AUTH_USER_KEY)
  localStorage.removeItem(AUTH_TOKEN_KEY)
  window.dispatchEvent(new Event(AUTH_USER_CHANGED_EVENT))
}

export const isAdmin = (): boolean => {
  const user = getAuthUser()
  return user?.role === 'admin' || user?.role === 'super_admin'
}

export const isSuperAdmin = (): boolean => {
  const user = getAuthUser()
  return user?.role === 'super_admin'
}

export const checkRegistrationEnabled = async (): Promise<boolean> => {
  try {
    const { data } = await api.get('/admin/configs/registration')
    return data.enabled
  } catch {
    return true // 默认开放注册
  }
}
