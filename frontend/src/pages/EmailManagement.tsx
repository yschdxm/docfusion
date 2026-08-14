import { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import { Inbox, RefreshCw, Send, Download, Mail, AlertCircle, Paperclip, ExternalLink, Copy, CheckCircle, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { agentMailService, type MailMessage, type MailAttachment, type SendMailPayload } from '../services/agentMailService'
import { useDocumentStore, type DocumentInfo } from '../stores/documentStore'
import { useI18n } from '../hooks/useI18n'
import { emailI18n } from '../services/i18n'
import MultiSelect from '../components/ui/MultiSelect'

// 允许导入的文件类型
const ALLOWED_IMPORT_EXTENSIONS = new Set(['docx', 'xlsx', 'pdf', 'txt', 'md'])

const msgId = (m: MailMessage) => String(m.id || m.message_id || '')
const dateText = (m: MailMessage) => String(m.date || m.received_at || '')

// 获取邮件内容和类型
const getContent = (m: MailMessage): { content: string; isHtml: boolean } => {
  // 检查 body 字段
  if (m.body && typeof m.body === 'string') {
    return { content: m.body, isHtml: m.body.trim().startsWith('<') }
  }
  if (m.text && typeof m.text === 'string') {
    return { content: m.text, isHtml: false }
  }
  if (m.snippet && typeof m.snippet === 'string') {
    return { content: m.snippet, isHtml: false }
  }

  // 检查 raw 字段
  if (m.raw) {
    if (typeof m.raw === 'string') {
      try {
        const parsed = JSON.parse(m.raw)
        if (parsed.body && typeof parsed.body === 'string') {
          return { content: parsed.body, isHtml: parsed.body.trim().startsWith('<') }
        }
        if (parsed.text && typeof parsed.text === 'string') return { content: parsed.text, isHtml: false }
        if (parsed.snippet && typeof parsed.snippet === 'string') return { content: parsed.snippet, isHtml: false }
        if (parsed.content && typeof parsed.content === 'string') {
          return { content: parsed.content, isHtml: parsed.content.trim().startsWith('<') }
        }
        return { content: '', isHtml: false }
      } catch {
        return { content: m.raw, isHtml: false }
      }
    }
    if (typeof m.raw === 'object') {
      const raw = m.raw as Record<string, unknown>
      if (typeof raw.body === 'string') {
        return { content: raw.body, isHtml: raw.body.trim().startsWith('<') }
      }
      if (typeof raw.text === 'string') return { content: raw.text, isHtml: false }
      if (typeof raw.snippet === 'string') return { content: raw.snippet, isHtml: false }
      if (typeof raw.content === 'string') {
        return { content: raw.content, isHtml: raw.content.trim().startsWith('<') }
      }
      if (raw.data && typeof raw.data === 'object') {
        const data = raw.data as Record<string, unknown>
        if (typeof data.body === 'string') {
          return { content: data.body, isHtml: data.body.trim().startsWith('<') }
        }
        if (typeof data.text === 'string') return { content: data.text, isHtml: false }
        if (typeof data.snippet === 'string') return { content: data.snippet, isHtml: false }
      }
      return { content: '', isHtml: false }
    }
  }

  return { content: '', isHtml: false }
}

// 获取附件的扩展名
const getAttachmentExt = (a: MailAttachment): string => {
  const filename = a.filename || a.name || ''
  const parts = filename.split('.')
  return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : ''
}

// 检查附件是否允许导入
const isAllowedAttachment = (a: MailAttachment): boolean => {
  const ext = getAttachmentExt(a)
  return ALLOWED_IMPORT_EXTENSIONS.has(ext)
}

// 复制到剪贴板的通用函数
const copyToClipboardFallback = async (text: string): Promise<boolean> => {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    } else {
      const textarea = document.createElement('textarea')
      textarea.value = text
      textarea.style.position = 'fixed'
      textarea.style.left = '-9999px'
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
      return true
    }
  } catch {
    return false
  }
}

// OAuth 授权组件
function AgentlyAuth({ onAuthComplete }: { onAuthComplete: () => void }) {
  const { language } = useI18n()
  const t = emailI18n[language]
  const [loading, setLoading] = useState(false)
  const [authData, setAuthData] = useState<{ auth_url: string; input_code: string; device_code: string; expires_in: number } | null>(null)
  const [polling, setPolling] = useState(false)
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [copied, setCopied] = useState<'link' | 'code' | null>(null)

  const startAuth = async () => {
    setLoading(true)
    try {
      const data = await agentMailService.startAuth()
      setAuthData(data)
      startPolling(data.device_code)
    } catch (error: any) {
      toast.error(error?.response?.data?.detail || t.startAuthFailed)
    } finally {
      setLoading(false)
    }
  }

  const startPolling = useCallback((deviceCode: string) => {
    setPolling(true)
    let stopped = false
    const pollInterval = setInterval(async () => {
      if (stopped) return
      try {
        const result = await agentMailService.pollAuth(deviceCode)
        // 并发的迟到响应（成功/失败已定局后才返回）直接忽略，避免误弹错误提示
        if (stopped) return
        if (result.status === 'completed') {
          stopped = true
          clearInterval(pollInterval)
          setPolling(false)
          toast.success(`${t.authSuccess}${result.email}`)
          onAuthComplete()
        } else if (result.status === 'expired' || result.status === 'error') {
          stopped = true
          clearInterval(pollInterval)
          setPolling(false)
          toast.error(result.error || t.authFailed)
        }
      } catch {
        // 继续轮询
      }
    }, 3000)
    pollIntervalRef.current = pollInterval

    setTimeout(() => {
      stopped = true
      clearInterval(pollInterval)
      setPolling(false)
    }, 600000)
  }, [onAuthComplete, t])

  // 组件卸载时清理轮询定时器，避免授权完成后孤儿定时器继续请求已消费的 device_code
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current)
        pollIntervalRef.current = null
      }
    }
  }, [])

  const handleCopy = async (text: string, type: 'link' | 'code') => {
    const success = await copyToClipboardFallback(text)
    if (success) {
      setCopied(type)
      setTimeout(() => setCopied(null), 2000)
      toast.success(t.copySuccess)
    } else {
      toast.error(t.copyFailed)
    }
  }

  return (
    <div className="flex h-full items-center justify-center bg-slate-50 dark:bg-slate-900">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-8 shadow-sm">
        <div className="text-center">
          <Mail className="mx-auto h-12 w-12 text-blue-600" />
          <h2 className="mt-4 text-xl font-semibold text-slate-900 dark:text-slate-100">{t.authTitle}</h2>
          <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">{t.authSubtitle}</p>
        </div>

        {!authData ? (
          <button
            onClick={startAuth}
            disabled={loading}
            className="mt-6 w-full rounded-xl bg-blue-600 px-4 py-3 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
          >
            {loading ? t.startingAuth : t.startAuth}
          </button>
        ) : (
          <div className="mt-6 space-y-4">
            <div className="rounded-xl border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/30 p-4">
              <p className="text-sm font-medium text-blue-800 dark:text-blue-300">{t.authSteps}</p>
              <ol className="mt-2 space-y-2 text-sm text-blue-700 dark:text-blue-400">
                <li>{t.step1}</li>
                <li>{t.step2}</li>
                <li>{t.step3}</li>
              </ol>
            </div>

            <div>
              <label className="text-xs font-medium text-slate-500 dark:text-slate-400">{t.authLink}</label>
              <div className="mt-1 flex items-center gap-2">
                <a
                  href={authData.auth_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex-1 truncate rounded-lg border border-slate-200 dark:border-slate-600 px-3 py-2 text-sm text-blue-600 dark:text-blue-400 hover:bg-slate-50 dark:hover:bg-slate-700"
                >
                  {authData.auth_url}
                </a>
                <button
                  onClick={() => handleCopy(authData.auth_url, 'link')}
                  className="rounded-lg border border-slate-200 dark:border-slate-600 p-2 text-slate-500 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-700"
                  title={t.copyLink}
                >
                  {copied === 'link' ? <CheckCircle className="h-4 w-4 text-green-500" /> : <Copy className="h-4 w-4" />}
                </button>
                <a
                  href={authData.auth_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="rounded-lg border border-slate-200 dark:border-slate-600 p-2 text-slate-500 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-700"
                  title={t.openInNewWindow}
                >
                  <ExternalLink className="h-4 w-4" />
                </a>
              </div>
            </div>

            <div>
              <label className="text-xs font-medium text-slate-500 dark:text-slate-400">{t.authCode}</label>
              <div className="mt-1 flex items-center gap-2">
                <div className="flex-1 rounded-lg border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-700 px-3 py-2 text-center text-lg font-mono font-bold text-slate-900 dark:text-slate-100">
                  {authData.input_code}
                </div>
                <button
                  onClick={() => handleCopy(authData.input_code, 'code')}
                  className="rounded-lg border border-slate-200 dark:border-slate-600 p-2 text-slate-500 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-700"
                  title={t.copyCode}
                >
                  {copied === 'code' ? <CheckCircle className="h-4 w-4 text-green-500" /> : <Copy className="h-4 w-4" />}
                </button>
              </div>
            </div>

            {polling && (
              <div className="flex items-center justify-center gap-2 rounded-lg bg-slate-50 dark:bg-slate-700 py-3 text-sm text-slate-600 dark:text-slate-300">
                <Loader2 className="h-4 w-4 animate-spin" />
                {t.waitingAuth}
              </div>
            )}

            <p className="text-center text-xs text-slate-400 dark:text-slate-500">
              {t.authCodeExpiry}{Math.floor(authData.expires_in / 60)} {t.minutes}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

interface PendingConfirmation {
  payload: SendMailPayload
  token: string
  summary: string
  raw: unknown
}

const pickConfirmationToken = (data: any) => (
  data?.confirmation_token
  || data?.confirmationToken
  || data?.data?.confirmation_token
  || data?.data?.confirmationToken
  || data?.raw?.confirmation_token
)

const pickConfirmationSummary = (data: any) => {
  const summary = data?.summary || data?.data?.summary || data?.message || data?.raw
  return typeof summary === 'string' ? summary : JSON.stringify(summary || data, null, 2)
}

export default function EmailManagement() {
  const { language } = useI18n()
  const t = emailI18n[language]
  const [status, setStatus] = useState<any>(null)
  const [authStatus, setAuthStatus] = useState<{ authorized: boolean; email?: string } | null>(null)
  const [messages, setMessages] = useState<MailMessage[]>([])
  const [selected, setSelected] = useState<MailMessage | null>(null)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [loading, setLoading] = useState(false)
  const [sending, setSending] = useState(false)
  const [importingId, setImportingId] = useState('')
  const [compose, setCompose] = useState({ to: '', subject: '', body: '' })
  const [selectedAttachments, setSelectedAttachments] = useState<DocumentInfo[]>([])
  const [pendingConfirmation, setPendingConfirmation] = useState<PendingConfirmation | null>(null)
  const { documents, fetchDocuments } = useDocumentStore()

  const selectedId = useMemo(() => selected ? msgId(selected) : '', [selected])
  const attachableDocuments = useMemo(
    () => documents.filter((doc) => doc.status !== 'deleted'),
    [documents],
  )

  const sender = (m: MailMessage) => {
    const from = m.from || m.sender
    if (!from) return t.unknownSender
    // 如果是对象（如 {name: "xxx", email: "xxx"}），提取 name 或 email
    if (typeof from === 'object' && from !== null) {
      const obj = from as Record<string, unknown>
      return String(obj.name || obj.email || obj.address || JSON.stringify(from))
    }
    return String(from)
  }

  const checkAuthStatus = async () => {
    try {
      const data = await agentMailService.getAuthStatus()
      setAuthStatus(data)
      return data.authorized
    } catch {
      setAuthStatus({ authorized: false })
      return false
    }
  }

  const loadStatus = async () => {
    const data = await agentMailService.status()
    setStatus(data)
    return data
  }

  const loadMessages = async () => {
    setLoading(true)
    try {
      const isAuthorized = await checkAuthStatus()
      if (!isAuthorized) {
        setLoading(false)
        return
      }

      await loadStatus()
      const data = await agentMailService.listMessages(30)
      const list = Array.isArray(data.messages) ? data.messages : []
      setMessages(list)

      // 自动选择第一个邮件并加载详情
      if (list.length > 0) {
        const firstMsg = list[0]
        setSelected(firstMsg)
        // 异步加载详情（包括附件）
        openMessage(firstMsg)
      }
    } catch (error: any) {
      toast.error(error?.response?.data?.detail || t.loadFailed)
    } finally {
      setLoading(false)
    }
  }

  const handleAuthComplete = () => {
    checkAuthStatus()
    loadMessages()
  }

  const openMessage = async (message: MailMessage) => {
    const id = msgId(message)
    setSelected(message)
    if (!id) return
    setLoadingDetail(true)
    try {
      const detail = await agentMailService.getMessage(id)
      // 合并数据，优先保留有效的 body
      const merged: MailMessage = {
        ...message,
        ...detail,
        // 确保 body 不会被覆盖为空或对象
        body: (typeof detail.body === 'string' && detail.body) ? detail.body
          : (typeof message.body === 'string' && message.body) ? message.body
          : undefined,
        text: (typeof detail.text === 'string' && detail.text) ? detail.text
          : (typeof message.text === 'string' ? message.text : undefined),
        snippet: (typeof detail.snippet === 'string' && detail.snippet) ? detail.snippet
          : (typeof message.snippet === 'string' ? message.snippet : undefined),
      }
      setSelected(merged)
    } catch {
      // 未配置详情命令时仍展示列表摘要
    } finally {
      setLoadingDetail(false)
    }
  }

  const sendMail = async () => {
    if (!compose.to.trim() || !compose.subject.trim()) {
      toast.error(t.fillRequired)
      return
    }

    const payload: SendMailPayload = {
      ...compose,
      attachments: [],
      document_ids: selectedAttachments.map((doc) => doc.id),
    }
    setSending(true)
    try {
      const data = await agentMailService.sendMessage(payload)
      const token = pickConfirmationToken(data)

      if (token) {
        setPendingConfirmation({
          payload,
          token: String(token),
          summary: pickConfirmationSummary(data),
          raw: data,
        })
        toast.success(t.pendingConfirm)
        return
      }

      toast.success(t.sendSuccess)
      setPendingConfirmation(null)
      setCompose({ to: '', subject: '', body: '' })
      setSelectedAttachments([])
    } catch (error: any) {
      toast.error(error?.response?.data?.detail || t.sendFailed)
    } finally {
      setSending(false)
    }
  }

  const confirmSendMail = async () => {
    if (!pendingConfirmation) return

    setSending(true)
    try {
      await agentMailService.confirmSendMessage({
        ...pendingConfirmation.payload,
        confirmation_token: pendingConfirmation.token,
      })
      toast.success(t.confirmSuccess)
      setPendingConfirmation(null)
      setCompose({ to: '', subject: '', body: '' })
    } catch (error: any) {
      toast.error(error?.response?.data?.detail || t.confirmFailed)
    } finally {
      setSending(false)
    }
  }

  const importAttachment = async (attachmentId: string, docCategory: 'source' | 'template' = 'source') => {
    if (!selectedId || !attachmentId) return
    setImportingId(attachmentId)
    try {
      const data = await agentMailService.importAttachment({ message_id: selectedId, attachment_id: attachmentId, doc_category: docCategory })
      toast.success(`${t.importSuccess} ${data.count || 0} ${t.importUnit}`)
      await fetchDocuments()
    } catch (error: any) {
      toast.error(error?.response?.data?.detail || t.importFailed)
    } finally {
      setImportingId('')
    }
  }

  useEffect(() => {
    checkAuthStatus().then((authorized) => {
      if (authorized) {
        loadMessages()
      }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 如果未授权，显示授权页面
  if (authStatus && !authStatus.authorized) {
    return <AgentlyAuth onAuthComplete={handleAuthComplete} />
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      {/* 头部 */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4 shadow-sm">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold text-slate-900 dark:text-slate-100">
            <Mail className="h-6 w-6 text-blue-600" />
            {t.title}
          </h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            {t.subtitle}
            {authStatus?.email && <span className="ml-2 text-blue-600 dark:text-blue-400">({authStatus.email})</span>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={loadMessages} disabled={loading} className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60">
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            {t.refresh}
          </button>
          <button
            onClick={async () => {
              await agentMailService.logoutAuth()
              setAuthStatus({ authorized: false })
              setMessages([])
              setSelected(null)
              toast.success(t.cancelAuthSuccess)
            }}
            className="inline-flex items-center gap-2 rounded-xl border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-4 py-2 text-sm font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-600"
          >
            {t.cancelAuth}
          </button>
        </div>
      </div>

      {/* 警告信息 */}
      {status && !status.authorized && (
        <div className="rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/30 p-4 text-sm text-amber-800 dark:text-amber-300">
          <div className="flex gap-2"><AlertCircle className="h-5 w-5" /><span>{t.notInstalled}</span></div>
          <pre className="mt-2 whitespace-pre-wrap rounded-lg bg-white/70 dark:bg-slate-800/70 p-3 text-xs">{status.error || ''}</pre>
        </div>
      )}

      {/* 主内容区 */}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[360px_1fr_360px]">
        {/* 收件箱 */}
        <section className="min-h-0 overflow-hidden rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 shadow-sm">
          <div className="flex items-center gap-2 border-b border-slate-100 dark:border-slate-700 p-4 font-semibold text-slate-900 dark:text-slate-100">
            <Inbox className="h-5 w-5" />
            {t.inbox}
          </div>
          <div className="h-full overflow-y-auto scrollbar-thin pb-16">
            {messages.map((m) => (
              <button
                key={msgId(m) || JSON.stringify(m).slice(0, 40)}
                onClick={() => openMessage(m)}
                className={`block w-full border-b border-slate-100 dark:border-slate-700 p-4 text-left hover:bg-slate-50 dark:hover:bg-slate-700/50 ${selectedId === msgId(m) ? 'bg-blue-50 dark:bg-blue-900/30' : ''}`}
              >
                <div className="truncate font-medium text-slate-900 dark:text-slate-100">{m.subject || t.noSubject}</div>
                <div className="mt-1 truncate text-sm text-slate-500 dark:text-slate-400">{sender(m)}</div>
                <div className="mt-1 text-xs text-slate-400 dark:text-slate-500">{dateText(m)}</div>
              </button>
            ))}
            {!messages.length && (
              <div className="p-6 text-center text-sm text-slate-500 dark:text-slate-400">
                {loading ? t.loading : t.noEmails}
              </div>
            )}
          </div>
        </section>

        {/* 邮件详情 */}
        <section className="min-h-0 overflow-y-auto scrollbar-thin rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-5 shadow-sm">
          {selected ? (
            <>
              <h2 className="text-xl font-semibold text-slate-900 dark:text-slate-100">{selected.subject || t.noSubject}</h2>
              <div className="mt-2 space-y-1 text-sm text-slate-500 dark:text-slate-400">
                <div>{t.sender}：{sender(selected)}</div>
                <div>{t.time}：{dateText(selected)}</div>
              </div>
              {(() => {
                const { content, isHtml } = getContent(selected)
                if (!content) return null
                if (isHtml) {
                  return (
                    <div
                      className="mt-5 rounded-xl bg-white dark:bg-slate-800 p-4 text-sm leading-6 text-slate-700 dark:text-slate-300
                        [&_a]:text-blue-600 [&_a]:underline [&_a]:dark:text-blue-400
                        [&_img]:max-w-full [&_img]:h-auto [&_img]:rounded-lg
                        [&_table]:w-full [&_table]:border-collapse [&_table]:my-2
                        [&_th]:border [&_th]:border-slate-300 [&_th]:dark:border-slate-600 [&_th]:px-3 [&_th]:py-2 [&_th]:bg-slate-100 [&_th]:dark:bg-slate-700
                        [&_td]:border [&_td]:border-slate-300 [&_td]:dark:border-slate-600 [&_td]:px-3 [&_td]:py-2
                        [&_h1]:text-xl [&_h1]:font-bold [&_h1]:my-3
                        [&_h2]:text-lg [&_h2]:font-semibold [&_h2]:my-2
                        [&_h3]:text-base [&_h3]:font-medium [&_h3]:my-2
                        [&_p]:my-2
                        [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:my-2
                        [&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:my-2
                        [&_blockquote]:border-l-4 [&_blockquote]:border-slate-300 [&_blockquote]:dark:border-slate-600 [&_blockquote]:pl-4 [&_blockquote]:my-2 [&_blockquote]:italic"
                      dangerouslySetInnerHTML={{ __html: content }}
                    />
                  )
                }
                return (
                  <div className="mt-5 whitespace-pre-wrap rounded-xl bg-slate-50 dark:bg-slate-700/50 p-4 text-sm leading-6 text-slate-700 dark:text-slate-300">
                    {content}
                  </div>
                )
              })()}

              {/* 附件区域 - 使用独立的加载状态 */}
              {loadingDetail ? (
                <div className="mt-5 flex items-center justify-center gap-2 py-4 text-sm text-slate-500 dark:text-slate-400">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t.loading}
                </div>
              ) : !!selected.attachments?.length && (() => {
                const allowedAttachments = selected.attachments.filter(isAllowedAttachment)
                if (allowedAttachments.length === 0) return null
                return (
                  <div className="mt-5">
                    <h3 className="mb-2 font-semibold text-slate-900 dark:text-slate-100">{t.attachments}</h3>
                    <div className="space-y-2">
                      {allowedAttachments.map((a) => {
                        const aid = String(a.id || a.attachment_id || a.filename || a.name || '')
                        const ext = getAttachmentExt(a)
                        return (
                          <div key={aid} className="rounded-xl border border-slate-200 dark:border-slate-600 p-3">
                            {/* 第一行：文件名和类型 */}
                            <div className="min-w-0 mb-2">
                              <div className="text-sm text-slate-700 dark:text-slate-300 break-all">{a.filename || a.name || aid}</div>
                              <div className="mt-0.5 text-xs text-slate-400 dark:text-slate-500 uppercase">{ext}</div>
                            </div>
                            {/* 第二行：操作按钮 */}
                            <div className="flex items-center gap-2">
                              <button
                                onClick={() => importAttachment(aid, 'source')}
                                disabled={importingId === aid}
                                className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-60"
                                title={t.importAsSource}
                              >
                                <Download className="h-3.5 w-3.5" />
                                {t.importAsSource}
                              </button>
                              <button
                                onClick={() => importAttachment(aid, 'template')}
                                disabled={importingId === aid}
                                className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-60"
                                title={t.importAsTemplate}
                              >
                                <Download className="h-3.5 w-3.5" />
                                {t.importAsTemplate}
                              </button>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )
              })()}
            </>
          ) : (
            <div className="flex h-full items-center justify-center text-slate-500 dark:text-slate-400">
              {t.selectEmail}
            </div>
          )}
        </section>

        {/* 发送邮件 */}
        <section className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-5 shadow-sm">
          <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900 dark:text-slate-100">
            <Send className="h-5 w-5" />
            {t.sendEmail}
          </h2>
          <div className="mt-4 min-h-0 flex-1 space-y-3 overflow-y-auto scrollbar-thin pr-1 pb-4">
            <input
              value={compose.to}
              onChange={(e) => { setPendingConfirmation(null); setCompose({ ...compose, to: e.target.value }) }}
              placeholder={t.to}
              className="w-full rounded-xl border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-sm text-slate-900 dark:text-slate-100 outline-none focus:border-blue-400 dark:focus:border-blue-500"
            />
            <input
              value={compose.subject}
              onChange={(e) => { setPendingConfirmation(null); setCompose({ ...compose, subject: e.target.value }) }}
              placeholder={t.subject}
              className="w-full rounded-xl border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-sm text-slate-900 dark:text-slate-100 outline-none focus:border-blue-400 dark:focus:border-blue-500"
            />
            <textarea
              value={compose.body}
              onChange={(e) => { setPendingConfirmation(null); setCompose({ ...compose, body: e.target.value }) }}
              placeholder={t.body}
              rows={6}
              className="w-full rounded-xl border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-sm text-slate-900 dark:text-slate-100 outline-none focus:border-blue-400 dark:focus:border-blue-500"
            />

            {/* 附件选择 */}
            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">
                <Paperclip className="inline h-4 w-4 mr-1" />
                {t.attachmentsLabel}
              </label>
              <MultiSelect
                values={selectedAttachments.map(doc => doc.id)}
                onChange={(ids) => {
                  setPendingConfirmation(null)
                  const newAttachments = attachableDocuments.filter(doc => ids.includes(doc.id))
                  setSelectedAttachments(newAttachments)
                }}
                options={attachableDocuments.map(doc => ({
                  value: doc.id,
                  label: doc.original_filename || doc.filename,
                  tag: doc.file_type,
                }))}
                placeholder={t.selectFromDocs}
                searchPlaceholder={t.selectFromDocs}
                maxHeight={200}
              />
            </div>

            {/* 确认发送 */}
            {pendingConfirmation && (
              <div className="rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/30 p-3 text-sm text-amber-900 dark:text-amber-300">
                <div className="font-semibold">{t.pendingConfirm}</div>
                <div className="mt-2 space-y-1 text-xs">
                  <div>{t.to}：{pendingConfirmation.payload.to}</div>
                  <div>{t.subject}：{pendingConfirmation.payload.subject}</div>
                </div>
                <pre className="mt-3 max-h-24 overflow-auto whitespace-pre-wrap rounded-lg bg-white/80 dark:bg-slate-800/80 p-3 text-xs text-slate-700 dark:text-slate-300">
                  {pendingConfirmation.summary}
                </pre>
                <div className="mt-3 grid grid-cols-2 gap-2">
                  <button
                    onClick={() => setPendingConfirmation(null)}
                    disabled={sending}
                    className="rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-xs font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-600 disabled:opacity-60"
                  >
                    {t.cancel}
                  </button>
                  <button
                    onClick={confirmSendMail}
                    disabled={sending}
                    className="rounded-lg bg-emerald-600 px-3 py-2 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-60"
                  >
                    {sending ? t.confirming : t.confirmSend}
                  </button>
                </div>
              </div>
            )}

            <button
              onClick={sendMail}
              disabled={sending}
              className="w-full rounded-xl bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
            >
              {sending ? t.processing : pendingConfirmation ? t.regenerateConfirm : t.send}
            </button>
          </div>
        </section>
      </div>
    </div>
  )
}
