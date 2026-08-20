import { FormEvent, useEffect, useMemo, useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { ArrowRight, Lock, Mail, Smartphone, UserRound, Sparkles, Shield } from 'lucide-react'
import toast from 'react-hot-toast'
import { isAxiosError } from 'axios'
import { isAuthenticated, registerWithPassword, checkRegistrationEnabled } from '../services/auth'
import { useI18n } from '../hooks/useI18n'

const registerI18n = {
  'zh-CN': {
    strengthTips: ['建议使用 8 位以上密码', '包含字母和数字更安全', '请避免使用常见弱密码'],
    brandBadge: '创建你的企业工作空间',
    heroTitle: '只需一分钟，开启智能办公体验',
    heroDesc: '注册后即可使用智能助手、自动填表和知识图谱分析。',
    securityTitle: '安全建议',
    registerTitle: '注册账号',
    registerSubtitle: '填写信息后将自动登录并进入系统。',
    accountLabel: '账号',
    accountPlaceholder: '请输入账号',
    emailLabel: '邮箱地址',
    phoneLabel: '手机号',
    phonePlaceholder: '请输入11位手机号',
    passwordLabel: '密码',
    passwordPlaceholder: '至少 6 位',
    confirmLabel: '确认密码',
    confirmPlaceholder: '再次输入密码',
    submitBtn: '注册并进入系统',
    submittingBtn: '注册中...',
    hasAccount: '已有账号？',
    backToLogin: '返回登录',
    disabledTitle: '注册功能已关闭',
    disabledDesc: '系统当前未开放注册，请联系管理员。',
    toastEmpty: '请完整填写注册信息',
    toastMismatch: '两次输入的密码不一致',
    toastShort: '密码长度至少 6 位',
    toastPhone: '手机号必须为11位数字',
    toastSuccess: '注册成功，已自动登录',
    toastFail: '注册失败，请稍后重试',
  },
  'en-US': {
    strengthTips: ['Use 8+ characters', 'Include letters and numbers', 'Avoid common weak passwords'],
    brandBadge: 'Create your workspace',
    heroTitle: 'Start smart office in one minute',
    heroDesc: 'Access smart assistant, auto-fill, and knowledge graph after registration.',
    securityTitle: 'Security Tips',
    registerTitle: 'Create Account',
    registerSubtitle: 'Fill in the form to auto-login and enter the system.',
    accountLabel: 'Username',
    accountPlaceholder: 'Enter username',
    emailLabel: 'Email',
    phoneLabel: 'Phone',
    phonePlaceholder: '11-digit phone number',
    passwordLabel: 'Password',
    passwordPlaceholder: 'At least 6 characters',
    confirmLabel: 'Confirm Password',
    confirmPlaceholder: 'Re-enter password',
    submitBtn: 'Register & Enter',
    submittingBtn: 'Registering...',
    hasAccount: 'Already have an account?',
    backToLogin: 'Back to login',
    disabledTitle: 'Registration Disabled',
    disabledDesc: 'Registration is currently closed. Please contact the admin.',
    toastEmpty: 'Please fill in all fields',
    toastMismatch: 'Passwords do not match',
    toastShort: 'Password must be at least 6 characters',
    toastPhone: 'Phone must be 11 digits',
    toastSuccess: 'Registration successful, auto-logged in',
    toastFail: 'Registration failed, please try again',
  },
  'ja-JP': {
    strengthTips: ['8文字以上で設定', '英字と数字を含める', '弱いパスワードは避ける'],
    brandBadge: 'ワークスペースを作成',
    heroTitle: '1分でスマートオフィスを開始',
    heroDesc: '登録後、スマートアシスタント・自動入力・ナレッジグラフをご利用いただけます。',
    securityTitle: 'セキュリティのヒント',
    registerTitle: 'アカウント登録',
    registerSubtitle: '情報を入力すると自動ログインします。',
    accountLabel: 'アカウント',
    accountPlaceholder: 'アカウントを入力',
    emailLabel: 'メールアドレス',
    phoneLabel: '電話番号',
    phonePlaceholder: '11桁の電話番号',
    passwordLabel: 'パスワード',
    passwordPlaceholder: '6文字以上',
    confirmLabel: 'パスワード確認',
    confirmPlaceholder: 'パスワードを再入力',
    submitBtn: '登録してシステムに入る',
    submittingBtn: '登録中...',
    hasAccount: 'アカウントをお持ちの方',
    backToLogin: 'ログインに戻る',
    disabledTitle: '登録は無効化されています',
    disabledDesc: '現在登録は受け付けていません。管理者にお問い合わせください。',
    toastEmpty: 'すべての項目を入力してください',
    toastMismatch: 'パスワードが一致しません',
    toastShort: 'パスワードは6文字以上必要です',
    toastPhone: '電話番号は11桁の数字です',
    toastSuccess: '登録成功。自動ログインしました',
    toastFail: '登録失敗。もう一度お試しください',
  },
} as const

export default function Register() {
  const navigate = useNavigate()
  const { language } = useI18n()
  const t = registerI18n[language]
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [registrationEnabled, setRegistrationEnabled] = useState<boolean | null>(null)

  const canSubmit = useMemo(
    () => Boolean(name.trim() && email.trim() && phone.trim() && password.trim() && confirmPassword.trim()),
    [name, email, phone, password, confirmPassword]
  )

  useEffect(() => {
    checkRegistrationEnabled().then(setRegistrationEnabled)
  }, [])

  if (isAuthenticated()) {
    return <Navigate to="/" replace />
  }

  if (registrationEnabled === false) {
    return (
      <div className="relative flex min-h-screen min-h-dvh items-center justify-center overflow-hidden bg-slate-950 p-6 md:p-10">
        <div className="auth-bg-grid" />
        <div className="relative z-10 mx-auto max-w-md rounded-2xl border border-white/15 bg-white/10 p-8 text-center backdrop-blur-xl">
          <h2 className="text-2xl font-semibold text-white">{t.disabledTitle}</h2>
          <p className="mt-3 text-sm text-slate-300">{t.disabledDesc}</p>
          <Link to="/login" className="mt-6 inline-block rounded-lg bg-blue-500 px-6 py-2 text-sm font-medium text-white hover:bg-blue-600">
            {t.backToLogin}
          </Link>
        </div>
      </div>
    )
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()

    if (!canSubmit) {
      toast.error(t.toastEmpty)
      return
    }

    if (password !== confirmPassword) {
      toast.error(t.toastMismatch)
      return
    }

    if (password.length < 6) {
      toast.error(t.toastShort)
      return
    }

    if (!/^\d{11}$/.test(phone.trim())) {
      toast.error(t.toastPhone)
      return
    }

    setIsSubmitting(true)
    try {
      await registerWithPassword(name, email, phone, password)
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
      <div className="auth-orb auth-orb-one left-1/4 top-[-10%] h-72 w-72 bg-indigo-500/30" />
      <div className="auth-orb auth-orb-two right-[-10%] top-1/4 h-80 w-80 bg-blue-500/25" />
      <div className="auth-orb auth-orb-three bottom-[-15%] left-[-8%] h-72 w-72 bg-emerald-500/20" />

      <div className="relative z-10 mx-auto max-w-5xl overflow-hidden rounded-[28px] border border-white/15 bg-white/10 shadow-[0_30px_80px_rgba(15,23,42,.55)] backdrop-blur-xl">
        <div className="lg:grid lg:grid-cols-5">
          <section className="border-b border-white/10 p-8 text-white lg:col-span-2 lg:border-b-0 lg:border-r lg:p-10 hidden lg:block">
            <div className="inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-3 py-1 text-xs font-medium">
              <Sparkles className="h-4 w-4" />
              {t.brandBadge}
            </div>
            <h1 className="mt-6 text-3xl font-semibold leading-tight">{t.heroTitle}</h1>
            <p className="mt-3 text-sm leading-6 text-slate-200">{t.heroDesc}</p>

            <div className="mt-8 rounded-xl border border-white/15 bg-white/10 p-4">
              <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                <Shield className="h-4 w-4 text-cyan-200" />
                {t.securityTitle}
              </div>
              <ul className="space-y-2 text-xs text-slate-200">
                {t.strengthTips.map((tip) => (
                  <li key={tip}>• {tip}</li>
                ))}
              </ul>
            </div>
          </section>

          <section className="bg-white p-6 sm:p-8 md:p-10 lg:col-span-3 lg:flex lg:items-center">
            <div className="w-full">
              <h2 className="text-2xl font-semibold text-slate-900">{t.registerTitle}</h2>
              <p className="mt-2 text-sm text-slate-500">{t.registerSubtitle}</p>

              <form onSubmit={handleSubmit} className="mt-8 space-y-4">
                <label className="block">
                  <span className="mb-2 block text-sm font-medium text-slate-700">{t.accountLabel}</span>
                  <div className="relative">
                    <UserRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                    <input
                      type="text"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder={t.accountPlaceholder}
                      className="input pl-10"
                    />
                  </div>
                </label>

                <label className="block">
                  <span className="mb-2 block text-sm font-medium text-slate-700">{t.emailLabel}</span>
                  <div className="relative">
                    <Mail className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                    <input
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="name@company.com"
                      className="input pl-10"
                    />
                  </div>
                </label>

                <label className="block">
                  <span className="mb-2 block text-sm font-medium text-slate-700">{t.phoneLabel}</span>
                  <div className="relative">
                    <Smartphone className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                    <input
                      type="tel"
                      inputMode="numeric"
                      pattern="\d{11}"
                      maxLength={11}
                      value={phone}
                      onChange={(e) => setPhone(e.target.value.replace(/\D/g, '').slice(0, 11))}
                      placeholder={t.phonePlaceholder}
                      className="input pl-10"
                    />
                  </div>
                </label>

                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
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

                  <label className="block">
                    <span className="mb-2 block text-sm font-medium text-slate-700">{t.confirmLabel}</span>
                    <div className="relative">
                      <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                      <input
                        type="password"
                        value={confirmPassword}
                        onChange={(e) => setConfirmPassword(e.target.value)}
                        placeholder={t.confirmPlaceholder}
                        className="input pl-10"
                      />
                    </div>
                  </label>
                </div>

                <button type="submit" disabled={!canSubmit || isSubmitting} className="btn-primary mt-2 w-full disabled:opacity-50" title={t.submitBtn}>
                  {isSubmitting ? t.submittingBtn : t.submitBtn}
                  {!isSubmitting && <ArrowRight className="h-4 w-4" />}
                </button>
              </form>

              <p className="mt-6 text-sm text-slate-500">
                {t.hasAccount}
                <Link to="/login" className="ml-1 font-medium text-primary-600 hover:text-primary-700">
                  {t.backToLogin}
                </Link>
              </p>
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
