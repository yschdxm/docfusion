import { useEffect, useMemo, useState } from 'react'
import { Inbox, RefreshCw, Send, Download, Mail, AlertCircle, Paperclip, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { agentMailService, type MailMessage, type SendMailPayload } from '../services/agentMailService'
import { useDocumentStore, type DocumentInfo } from '../stores/documentStore'

const msgId = (m: MailMessage) => String(m.id || m.message_id || '')
const sender = (m: MailMessage) => String(m.from || m.sender || '未知发件人')
const dateText = (m: MailMessage) => String(m.date || m.received_at || '')
const contentText = (m: MailMessage) => String(m.body || m.text || m.snippet || m.raw || '')

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
  const [status, setStatus] = useState<any>(null)
  const [messages, setMessages] = useState<MailMessage[]>([])
  const [selected, setSelected] = useState<MailMessage | null>(null)
  const [loading, setLoading] = useState(false)
  const [sending, setSending] = useState(false)
  const [importingId, setImportingId] = useState('')
  const [compose, setCompose] = useState({ to: '', subject: '', body: '' })
  const [selectedAttachments, setSelectedAttachments] = useState<DocumentInfo[]>([])
  const [showAttachmentPicker, setShowAttachmentPicker] = useState(false)
  const [pendingConfirmation, setPendingConfirmation] = useState<PendingConfirmation | null>(null)
  const { documents, fetchDocuments } = useDocumentStore()

  const selectedId = useMemo(() => selected ? msgId(selected) : '', [selected])
  const attachableDocuments = useMemo(
    () => documents.filter((doc) => doc.status !== 'deleted'),
    [documents],
  )

  const loadStatus = async () => {
    const data = await agentMailService.status()
    setStatus(data)
    return data
  }

  const loadMessages = async () => {
    setLoading(true)
    try {
      await loadStatus()
      const data = await agentMailService.listMessages(30)
      const list = Array.isArray(data.messages) ? data.messages : []
      setMessages(list)
      if (list.length && !selected) setSelected(list[0])
    } catch (error: any) {
      toast.error(error?.response?.data?.detail || '邮件列表加载失败')
    } finally {
      setLoading(false)
    }
  }

  const openMessage = async (message: MailMessage) => {
    const id = msgId(message)
    setSelected(message)
    if (!id) return
    try {
      const detail = await agentMailService.getMessage(id)
      setSelected({ ...message, ...detail })
    } catch {
      // 未配置详情命令时仍展示列表摘要
    }
  }

  const sendMail = async () => {
    if (!compose.to.trim() || !compose.subject.trim()) {
      toast.error('请填写收件人和主题')
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
        toast.success('请确认邮件摘要后完成发送')
        return
      }

      toast.success('邮件已发送')
      setPendingConfirmation(null)
      setCompose({ to: '', subject: '', body: '' })
      setSelectedAttachments([])
      setShowAttachmentPicker(false)
      setSelectedAttachments([])
      setShowAttachmentPicker(false)
    } catch (error: any) {
      toast.error(error?.response?.data?.detail || '发送失败，请检查命令模板配置')
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
      toast.success('邮件发送成功')
      setPendingConfirmation(null)
      setCompose({ to: '', subject: '', body: '' })
    } catch (error: any) {
      toast.error(error?.response?.data?.detail || '确认发送失败')
    } finally {
      setSending(false)
    }
  }

  const toggleDocumentAttachment = (doc: DocumentInfo) => {
    setPendingConfirmation(null)
    setSelectedAttachments((current) => (
      current.some((item) => item.id === doc.id)
        ? current.filter((item) => item.id !== doc.id)
        : [...current, doc]
    ))
  }

  const removeDocumentAttachment = (docId: string) => {
    setPendingConfirmation(null)
    setSelectedAttachments((current) => current.filter((item) => item.id !== docId))
  }

  const openAttachmentPicker = async () => {
    setShowAttachmentPicker((open) => !open)
    if (!documents.length) {
      await fetchDocuments()
    }
  }

  const importAttachment = async (attachmentId: string) => {
    if (!selectedId || !attachmentId) return
    setImportingId(attachmentId)
    try {
      const data = await agentMailService.importAttachment({ message_id: selectedId, attachment_id: attachmentId, doc_category: 'source' })
      toast.success(`已导入 ${data.count || 0} 个附件到文件上传/文档管理`)
      await fetchDocuments()
    } catch (error: any) {
      toast.error(error?.response?.data?.detail || '附件导入失败')
    } finally {
      setImportingId('')
    }
  }

  useEffect(() => {
    loadMessages()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold text-slate-900">
            <Mail className="h-6 w-6 text-blue-600" />
            邮件管理
          </h1>
          <p className="mt-1 text-sm text-slate-500">腾讯 Agent Mail 邮件收发、阅读与附件导入</p>
        </div>
        <button onClick={loadMessages} disabled={loading} className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60">
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          刷新
        </button>
      </div>

      {status && !status.authorized && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          <div className="flex gap-2"><AlertCircle className="h-5 w-5" /><span>尚未完成 Agent Mail 授权或后端未安装 agently-cli。</span></div>
          <pre className="mt-2 whitespace-pre-wrap rounded-lg bg-white/70 p-3 text-xs">{status.error || '请在后端环境执行 agently-cli auth login 与 agently-cli +me'}</pre>
        </div>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[360px_1fr_360px]">
        <section className="min-h-0 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="flex items-center gap-2 border-b border-slate-100 p-4 font-semibold"><Inbox className="h-5 w-5" />收件箱</div>
          <div className="h-full overflow-auto pb-16">
            {messages.map((m) => (
              <button key={msgId(m) || JSON.stringify(m).slice(0, 40)} onClick={() => openMessage(m)} className={`block w-full border-b border-slate-100 p-4 text-left hover:bg-slate-50 ${selectedId === msgId(m) ? 'bg-blue-50' : ''}`}>
                <div className="truncate font-medium text-slate-900">{m.subject || '无主题'}</div>
                <div className="mt-1 truncate text-sm text-slate-500">{sender(m)}</div>
                <div className="mt-1 text-xs text-slate-400">{dateText(m)}</div>
              </button>
            ))}
            {!messages.length && <div className="p-6 text-center text-sm text-slate-500">{loading ? '加载中...' : '暂无邮件或未配置列表命令'}</div>}
          </div>
        </section>

        <section className="min-h-0 overflow-auto rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          {selected ? (
            <>
              <h2 className="text-xl font-semibold text-slate-900">{selected.subject || '无主题'}</h2>
              <div className="mt-2 space-y-1 text-sm text-slate-500">
                <div>发件人：{sender(selected)}</div>
                <div>时间：{dateText(selected)}</div>
              </div>
              <div className="mt-5 whitespace-pre-wrap rounded-xl bg-slate-50 p-4 text-sm leading-6 text-slate-700">{contentText(selected)}</div>
              {!!selected.attachments?.length && (
                <div className="mt-5">
                  <h3 className="mb-2 font-semibold">附件</h3>
                  <div className="space-y-2">
                    {selected.attachments.map((a) => {
                      const aid = String(a.id || a.attachment_id || a.filename || a.name || '')
                      return (
                        <div key={aid} className="flex items-center justify-between rounded-xl border border-slate-200 p-3">
                          <span className="truncate text-sm">{a.filename || a.name || aid}</span>
                          <button onClick={() => importAttachment(aid)} disabled={importingId === aid} className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-60">
                            <Download className="h-3.5 w-3.5" />导入系统
                          </button>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </>
          ) : <div className="flex h-full items-center justify-center text-slate-500">请选择一封邮件</div>}
        </section>

        <section className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="flex items-center gap-2 text-lg font-semibold"><Send className="h-5 w-5" />发送邮件</h2>
          <div className="mt-4 min-h-0 flex-1 space-y-3 overflow-y-auto pr-1 pb-4">
            <input value={compose.to} onChange={(e) => { setPendingConfirmation(null); setCompose({ ...compose, to: e.target.value }) }} placeholder="收件人邮箱" className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:border-blue-400" />
            <input value={compose.subject} onChange={(e) => { setPendingConfirmation(null); setCompose({ ...compose, subject: e.target.value }) }} placeholder="主题" className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:border-blue-400" />
            <textarea value={compose.body} onChange={(e) => { setPendingConfirmation(null); setCompose({ ...compose, body: e.target.value }) }} placeholder="正文" rows={6} className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:border-blue-400" />

            <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
              <div className="flex items-center justify-between gap-2">
                <div className="text-sm font-medium text-slate-700">附件</div>
                <button
                  type="button"
                  onClick={openAttachmentPicker}
                  className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-100"
                >
                  <Paperclip className="h-3.5 w-3.5" />
                  {showAttachmentPicker ? '收起选择' : '从文档管理选择'}
                </button>
              </div>

              {!!selectedAttachments.length && (
                <div className="mt-3 space-y-2">
                  {selectedAttachments.map((doc) => (
                    <div key={doc.id} className="flex items-center justify-between gap-2 rounded-lg bg-white px-3 py-2 text-xs text-slate-700">
                      <span className="min-w-0 flex-1 truncate">{doc.original_filename || doc.filename}</span>
                      <button
                        type="button"
                        onClick={() => removeDocumentAttachment(doc.id)}
                        className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                        title="移除附件"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {showAttachmentPicker && (
                <div className="mt-3 max-h-36 overflow-auto rounded-lg border border-slate-200 bg-white">
                  {attachableDocuments.map((doc) => {
                    const checked = selectedAttachments.some((item) => item.id === doc.id)
                    return (
                      <label key={doc.id} className="flex cursor-pointer items-center gap-2 border-b border-slate-100 px-3 py-2 text-xs hover:bg-slate-50">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleDocumentAttachment(doc)}
                          className="h-3.5 w-3.5 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                        />
                        <span className="min-w-0 flex-1 truncate">{doc.original_filename || doc.filename}</span>
                        <span className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] uppercase text-slate-500">{doc.file_type}</span>
                      </label>
                    )
                  })}
                  {!attachableDocuments.length && (
                    <div className="px-3 py-4 text-center text-xs text-slate-500">文档管理中暂无可选文件</div>
                  )}
                </div>
              )}
            </div>

            {pendingConfirmation && (
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                <div className="font-semibold">待确认发送</div>
                <div className="mt-2 space-y-1 text-xs">
                  <div>收件人：{pendingConfirmation.payload.to}</div>
                  <div>主题：{pendingConfirmation.payload.subject}</div>
                  <div>附件：{pendingConfirmation.payload.document_ids?.length || 0} 个文档</div>
                </div>
                <pre className="mt-3 max-h-24 overflow-auto whitespace-pre-wrap rounded-lg bg-white/80 p-3 text-xs text-slate-700">{pendingConfirmation.summary}</pre>
                <div className="mt-3 grid grid-cols-2 gap-2">
                  <button onClick={() => setPendingConfirmation(null)} disabled={sending} className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60">
                    取消
                  </button>
                  <button onClick={confirmSendMail} disabled={sending} className="rounded-lg bg-emerald-600 px-3 py-2 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-60">
                    {sending ? '确认中...' : '确认发送'}
                  </button>
                </div>
              </div>
            )}

            <button onClick={sendMail} disabled={sending} className="w-full rounded-xl bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60">{sending ? '处理中...' : pendingConfirmation ? '重新生成确认' : '发送'}</button>
          </div>
        </section>
      </div>
    </div>
  )
}
