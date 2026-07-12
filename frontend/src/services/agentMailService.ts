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
}
