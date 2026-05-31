import { FormEvent, useMemo, useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { ArrowRight, Lock, Mail, Smartphone, UserRound, Sparkles, Shield } from 'lucide-react'
import toast from 'react-hot-toast'
import { isAxiosError } from 'axios'
import { isAuthenticated, registerWithPassword } from '../services/auth'

const strengthTips = ['建议使用 8 位以上密码', '包含字母和数字更安全', '请避免使用常见弱密码']

export default function Register() {
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  const canSubmit = useMemo(
    () => Boolean(name.trim() && email.trim() && phone.trim() && password.trim() && confirmPassword.trim()),
    [name, email, phone, password, confirmPassword]
  )

  if (isAuthenticated()) {
    return <Navigate to="/" replace />
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()

    if (!canSubmit) {
      toast.error('请完整填写注册信息')
      return
    }

    if (password !== confirmPassword) {
      toast.error('两次输入的密码不一致')
      return
    }

    if (password.length < 6) {
      toast.error('密码长度至少 6 位')
      return
    }

    if (!/^\d{11}$/.test(phone.trim())) {
      toast.error('手机号必须为11位数字')
      return
    }

    setIsSubmitting(true)
    try {
      await registerWithPassword(name, email, phone, password)
      toast.success('注册成功，已自动登录')
      navigate('/')
    } catch (error: unknown) {
      const message = isAxiosError(error) ? error.response?.data?.detail : ''
      toast.error(typeof message === 'string' && message ? message : '注册失败，请稍后重试')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-slate-950 p-6 md:p-10">
      <div className="auth-bg-grid" />
      <div className="auth-orb auth-orb-one left-1/4 top-[-10%] h-72 w-72 bg-indigo-500/30" />
      <div className="auth-orb auth-orb-two right-[-10%] top-1/4 h-80 w-80 bg-blue-500/25" />
      <div className="auth-orb auth-orb-three bottom-[-15%] left-[-8%] h-72 w-72 bg-emerald-500/20" />

      <div className="relative z-10 mx-auto max-w-5xl overflow-hidden rounded-[28px] border border-white/15 bg-white/10 shadow-[0_30px_80px_rgba(15,23,42,.55)] backdrop-blur-xl">
        <div className="lg:grid lg:grid-cols-5">
          <section className="border-b border-white/10 p-8 text-white lg:col-span-2 lg:border-b-0 lg:border-r lg:p-10 hidden lg:block">
            <div className="inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-3 py-1 text-xs font-medium">
              <Sparkles className="h-4 w-4" />
              创建你的企业工作空间
            </div>
            <h1 className="mt-6 text-3xl font-semibold leading-tight">只需一分钟，开启智能办公体验</h1>
            <p className="mt-3 text-sm leading-6 text-slate-200">注册后即可使用智能助手、自动填表和知识图谱分析。</p>

            <div className="mt-8 rounded-xl border border-white/15 bg-white/10 p-4">
              <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                <Shield className="h-4 w-4 text-cyan-200" />
                安全建议
              </div>
              <ul className="space-y-2 text-xs text-slate-200">
                {strengthTips.map((tip) => (
                  <li key={tip}>• {tip}</li>
                ))}
              </ul>
            </div>
          </section>

          <section className="bg-white p-6 sm:p-8 md:p-10 lg:col-span-3 lg:flex lg:items-center">
            <div className="w-full">
              <h2 className="text-2xl font-semibold text-slate-900">注册账号</h2>
              <p className="mt-2 text-sm text-slate-500">填写信息后将自动登录并进入系统。</p>

              <form onSubmit={handleSubmit} className="mt-8 space-y-4">
                <label className="block">
                  <span className="mb-2 block text-sm font-medium text-slate-700">账号</span>
                  <div className="relative">
                    <UserRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                    <input
                      type="text"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder="请输入账号"
                      className="input pl-10"
                    />
                  </div>
                </label>

                <label className="block">
                  <span className="mb-2 block text-sm font-medium text-slate-700">邮箱地址</span>
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
                  <span className="mb-2 block text-sm font-medium text-slate-700">手机号</span>
                  <div className="relative">
                    <Smartphone className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                    <input
                      type="tel"
                      inputMode="numeric"
                      pattern="\d{11}"
                      maxLength={11}
                      value={phone}
                      onChange={(e) => setPhone(e.target.value.replace(/\D/g, '').slice(0, 11))}
                      placeholder="请输入11位手机号"
                      className="input pl-10"
                    />
                  </div>
                </label>

                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <label className="block">
                    <span className="mb-2 block text-sm font-medium text-slate-700">密码</span>
                    <div className="relative">
                      <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                      <input
                        type="password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        placeholder="至少 6 位"
                        className="input pl-10"
                      />
                    </div>
                  </label>

                  <label className="block">
                    <span className="mb-2 block text-sm font-medium text-slate-700">确认密码</span>
                    <div className="relative">
                      <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                      <input
                        type="password"
                        value={confirmPassword}
                        onChange={(e) => setConfirmPassword(e.target.value)}
                        placeholder="再次输入密码"
                        className="input pl-10"
                      />
                    </div>
                  </label>
                </div>

                <button type="submit" disabled={!canSubmit || isSubmitting} className="btn-primary mt-2 w-full disabled:opacity-50">
                  {isSubmitting ? '注册中...' : '注册并进入系统'}
                  {!isSubmitting && <ArrowRight className="h-4 w-4" />}
                </button>
              </form>

              <p className="mt-6 text-sm text-slate-500">
                已有账号？
                <Link to="/login" className="ml-1 font-medium text-primary-600 hover:text-primary-700">
                  返回登录
                </Link>
              </p>
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
