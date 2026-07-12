import api from './api'

export interface MailAttachment {
  id?: string
  attachment_id?: string
  name?: string
  filename?: string
  size?: number
}

export interface MailMessage {
  id?: string
  message_id?: string
  subject?: string
  from?: string
  sender?: string
  to?: string | string[]
  date?: string
  received_at?: string
  body?: string
  text?: string
  html?: string
  snippet?: string
  attachments?: MailAttachment[]
  raw?: unknown
}

export interface SendMailPayload {
  to: string
  subject: string
  body: string
  attachments?: string[]
  document_ids?: string[]
}

export interface OAuthStartResponse {
  auth_url: string
  input_code: string
  device_code: string
  expires_in: number
  message?: string
}

export interface OAuthPollResponse {
  status: 'pending' | 'completed' | 'expired' | 'error'
  email?: string
  error?: string
}

export const agentMailService = {
  async status() {
    const { data } = await api.get('/agent-mail/status')
    return data
  },
  async listMessages(limit = 20) {
    const { data } = await api.get('/agent-mail/messages', { params: { limit } })
    return data
  },
  async getMessage(messageId: string) {
    const { data } = await api.get(`/agent-mail/messages/${encodeURIComponent(messageId)}`)
    return data
  },
  async sendMessage(payload: SendMailPayload) {
    const { data } = await api.post('/agent-mail/send', payload)
    return data
  },
  async confirmSendMessage(payload: SendMailPayload & { confirmation_token: string }) {
    const { data } = await api.post('/agent-mail/send/confirm', payload)
    return data
  },
  async importAttachment(payload: { message_id: string; attachment_id: string; doc_category?: 'source' | 'template' }) {
    const { data } = await api.post('/agent-mail/attachments/import', payload)
    return data
  },

  // ==================== OAuth 授权 ====================

  async getAuthStatus(): Promise<{ authorized: boolean; email?: string }> {
    const { data } = await api.get('/agent-mail/auth/status')
    return data
  },

  async startAuth(): Promise<OAuthStartResponse> {
    const { data } = await api.post('/agent-mail/auth/start')
    return data
  },

  async pollAuth(deviceCode: string): Promise<OAuthPollResponse> {
    const { data } = await api.post('/agent-mail/auth/poll', null, {
      params: { device_code: deviceCode },
    })
    return data
  },

  async logoutAuth(): Promise<{ success: boolean; message: string }> {
    const { data } = await api.post('/agent-mail/auth/logout')
    return data
  },
}
