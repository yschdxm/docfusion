import { FormEvent, useEffect, useMemo, useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { ArrowRight, Lock, Mail, ShieldCheck, Sparkles, Building2, CheckCircle2, Smartphone } from 'lucide-react'
import toast from 'react-hot-toast'
import { isAxiosError } from 'axios'
import { isAuthenticated, loginWithPassword, checkRegistrationEnabled } from '../services/auth'
import { useI18n } from '../hooks/useI18n'

const loginI18n = {
  'zh-CN': {
    highlights: ['企业级文档流转', '多源数据融合处理', '任务状态可追踪'],
    brandBadge: '知融云枢 智能办公平台',
    heroTitle: '让复杂文档处理',
    heroSubtitle: '变成标准化工作流',
    heroDesc: '统一管理文档、智能提取信息、自动填充模板、构建知识图谱，打造企业级一体化文档中台。',
    enterpriseTitle: '企业安全访问',
    enterpriseDesc: '支持账号隔离、权限边界与操作留痕',
    loginTitle: '登录系统',
    loginSubtitle: '欢迎回来，请输入账号信息继续。',
    accountLabel: '邮箱或手机号',
    accountPlaceholder: 'name@company.com 或 13800138000',
    passwordLabel: '密码',
    passwordPlaceholder: '请输入密码',
    submitBtn: '进入工作台',
    submittingBtn: '登录中...',
    protected: '受保护的连接',
    registerLink: '没有账号？立即注册',
    toastEmpty: '请输入邮箱或手机号及密码',
    toastFormat: '账号需为邮箱或11位手机号',
    toastSuccess: '登录成功',
    toastFail: '登录失败，请检查账号和密码',
  },
  'en-US': {
    highlights: ['Enterprise document workflow', 'Multi-source data fusion', 'Trackable task status'],
    brandBadge: 'ZhiRong Hub Smart Office',
    heroTitle: 'Turn complex docs',
    heroSubtitle: 'into standardized workflows',
    heroDesc: 'Unified doc management, smart extraction, auto-fill templates, and knowledge graphs — an enterprise-grade document hub.',
    enterpriseTitle: 'Enterprise Security',
    enterpriseDesc: 'Account isolation, permission boundaries, and operation traces',
    loginTitle: 'Sign In',
    loginSubtitle: 'Welcome back, enter your credentials to continue.',
    accountLabel: 'Email or Phone',
    accountPlaceholder: 'name@company.com or 13800138000',
    passwordLabel: 'Password',
    passwordPlaceholder: 'Enter your password',
    submitBtn: 'Enter Workspace',
    submittingBtn: 'Signing in...',
    protected: 'Protected connection',
    registerLink: 'No account? Register now',
    toastEmpty: 'Please enter email/phone and password',
    toastFormat: 'Account must be email or 11-digit phone number',
    toastSuccess: 'Login successful',
    toastFail: 'Login failed, please check your credentials',
  },
  'ja-JP': {
    highlights: ['エンタープライズ文書ワークフロー', '多源データ融合処理', '追跡可能なタスクステータス'],
    brandBadge: '知融云枢 スマートオフィス',
    heroTitle: '複雑な文書処理を',
    heroSubtitle: '標準化ワークフローに',
    heroDesc: '文書管理・情報抽出・テンプレート自動入力・ナレッジグラフを統合したエンタープライズ文書基盤です。',
    enterpriseTitle: 'エンタープライズセキュリティ',
    enterpriseDesc: 'アカウント分離、権限境界、操作履跡に対応',
    loginTitle: 'ログイン',
    loginSubtitle: 'おかえりなさい。資格情報を入力してください。',
    accountLabel: 'メールまたは電話番号',
    accountPlaceholder: 'name@company.com または 13800138000',
    passwordLabel: 'パスワード',
    passwordPlaceholder: 'パスワードを入力',
    submitBtn: 'ワークスペースに入る',
    submittingBtn: 'ログイン中...',
    protected: '保護された接続',
    registerLink: 'アカウントをお持ちでない方は新規登録',
    toastEmpty: 'メール/電話番号とパスワードを入力してください',
    toastFormat: 'メールアドレスまたは11桁の電話番号を入力してください',
    toastSuccess: 'ログイン成功',
    toastFail: 'ログイン失敗。資格情報を確認してください',
  },
} as const

export default function Login() {
  const navigate = useNavigate()
  const { language } = useI18n()
  const t = loginI18n[language]
  const [account, setAccount] = useState('')
  const [password, setPassword] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [registrationEnabled, setRegistrationEnabled] = useState(true)

  const canSubmit = useMemo(() => Boolean(account.trim() && password.trim()), [account, password])

  useEffect(() => {
    checkRegistrationEnabled().then(setRegistrationEnabled)
  }, [])

  if (isAuthenticated()) {
    return <Navigate to="/" replace />
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()

    if (!canSubmit) {
      toast.error(t.toastEmpty)
      return
    }

    const normalized = account.trim()
    const isEmail = /\S+@\S+\.\S+/.test(normalized)
    const isPhone = /^\d{11}$/.test(normalized)
    if (!isEmail && !isPhone) {
      toast.error(t.toastFormat)
      return
    }

    setIsSubmitting(true)
    try {
      await loginWithPassword(account, password)
      toast.success(t.toastSuccess)
      navigate('/')
    } catch (error: unknown) {
      const message = isAxiosError(error) ? error.response?.data?.detail : ''
      toast.error(typeof message === 'string' && message ? message : t.toastFail)
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="relative flex min-h-screen min-h-dvh items-center justify-center overflow-hidden bg-slate-950 p-6 md:p-10">
      <div className="auth-bg-grid" />
      <div className="auth-orb auth-orb-one -left-24 -top-24 h-72 w-72 bg-blue-500/30" />
      <div className="auth-orb auth-orb-two -right-28 top-1/3 h-80 w-80 bg-cyan-400/20" />
      <div className="auth-orb auth-orb-three bottom-0 left-1/3 h-72 w-72 bg-emerald-400/20" />

      <div className="relative z-10 mx-auto max-w-6xl overflow-hidden rounded-[28px] border border-white/15 bg-white/10 shadow-[0_30px_80px_rgba(15,23,42,.55)] backdrop-blur-xl lg:grid lg:grid-cols-2">
        <section className="relative p-8 text-white md:p-10 lg:p-12 hidden lg:block">
          <div className="inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-3 py-1 text-xs font-medium">
            <Sparkles className="h-4 w-4" />
            {t.brandBadge}
          </div>

          <h1 className="mt-6 text-3xl font-semibold leading-tight md:text-4xl">
            {t.heroTitle}
            <span className="block bg-gradient-to-r from-cyan-300 via-blue-200 to-emerald-200 bg-clip-text text-transparent">{t.heroSubtitle}</span>
          </h1>

          <p className="mt-4 max-w-md text-sm leading-6 text-slate-200">
            {t.heroDesc}
          </p>

          <div className="mt-8 space-y-3">
            {t.highlights.map((item) => (
              <div key={item} className="flex items-center gap-2 text-sm text-slate-100">
                <CheckCircle2 className="h-4 w-4 text-emerald-300" />
                {item}
              </div>
            ))}
          </div>

          <div className="mt-10 rounded-xl border border-white/15 bg-white/10 p-4">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/15">
                <Building2 className="h-5 w-5" />
              </div>
              <div>
                <p className="text-sm font-medium">{t.enterpriseTitle}</p>
                <p className="text-xs text-slate-200">{t.enterpriseDesc}</p>
              </div>
            </div>
          </div>
        </section>

        <section className="bg-white p-6 sm:p-8 md:p-10 lg:p-12 lg:flex lg:items-center">
          <div className="mx-auto w-full max-w-md">
            <h2 className="text-2xl font-semibold text-slate-900">{t.loginTitle}</h2>
            <p className="mt-2 text-sm text-slate-500">{t.loginSubtitle}</p>

            <form onSubmit={handleSubmit} className="mt-8 space-y-5">
              <label className="block">
                <span className="mb-2 block text-sm font-medium text-slate-700">{t.accountLabel}</span>
                <div className="relative">
                  <div className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">
                    {/\S+@\S+\.\S+/.test(account.trim()) ? <Mail className="h-4 w-4" /> : <Smartphone className="h-4 w-4" />}
                  </div>
                  <input
                    type="text"
                    value={account}
                    onChange={(e) => setAccount(e.target.value)}
                    placeholder={t.accountPlaceholder}
                    className="input pl-10"
                  />
                </div>
              </label>

              <label className="block">
                <span className="mb-2 block text-sm font-medium text-slate-700">{t.passwordLabel}</span>
                <div className="relative">
                  <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder={t.passwordPlaceholder}
                    className="input pl-10"
                  />
                </div>
              </label>

              <button type="submit" disabled={!canSubmit || isSubmitting} className="btn-primary w-full disabled:opacity-50" title={t.submitBtn}>
                {isSubmitting ? t.submittingBtn : t.submitBtn}
                {!isSubmitting && <ArrowRight className="h-4 w-4" />}
              </button>
            </form>

            <div className="mt-6 flex items-center justify-between text-xs text-slate-500">
              <span className="inline-flex items-center gap-1">
                <ShieldCheck className="h-3.5 w-3.5" />
                {t.protected}
              </span>
              {registrationEnabled && (
                <Link to="/register" className="font-medium text-primary-600 hover:text-primary-700">
                  {t.registerLink}
                </Link>
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}
