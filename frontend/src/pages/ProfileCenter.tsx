import { FormEvent, useMemo, useState } from 'react'
import { BadgeCheck, KeyRound, Mail, Phone, Save, Shield } from 'lucide-react'
import { isAxiosError } from 'axios'
import toast from 'react-hot-toast'
import { changePassword, getAuthUser, getLastLoginAt, updateAuthUser } from '../services/auth'
import { profileI18n } from '../services/i18n'
import { useI18n } from '../hooks/useI18n'

const roleLabels = {
  'zh-CN': { user: '普通用户', admin: '管理员', super_admin: '主管理员' },
  'en-US': { user: 'Standard User', admin: 'Admin', super_admin: 'Super Admin' },
  'ja-JP': { user: '一般ユーザー', admin: '管理者', super_admin: '主管理者' },
}

const AVATAR_SEED_KEY = 'profile_avatar_seed'

const avatarPresets = [
  { icon: 'A', from: '#60a5fa', to: '#2563eb' },
  { icon: 'B', from: '#22d3ee', to: '#0ea5e9' },
  { icon: 'C', from: '#fb7185', to: '#f97316' },
  { icon: 'D', from: '#a78bfa', to: '#6366f1' },
  { icon: 'E', from: '#f59e0b', to: '#ea580c' },
  { icon: 'F', from: '#14b8a6', to: '#0f766e' },
  { icon: 'G', from: '#818cf8', to: '#4338ca' },
  { icon: 'H', from: '#34d399', to: '#10b981' },
]

const ensureAvatarSeed = () => {
  const existed = localStorage.getItem(AVATAR_SEED_KEY)
  if (existed) return Number(existed)
  const generated = Math.floor(Math.random() * avatarPresets.length)
  localStorage.setItem(AVATAR_SEED_KEY, `${generated}`)
  return generated
}

const buildUserId = (seed: string) => {
  let hash = 0
  for (let i = 0; i < seed.length; i += 1) hash = (hash * 31 + seed.charCodeAt(i)) % 1000000
  return `${hash}`.padStart(6, '0')
}

export default function ProfileCenter() {
  const { language } = useI18n()
  const t = profileI18n[language]
  const tr = (zh: string, en: string, ja = en) => (language === 'zh-CN' ? zh : language === 'ja-JP' ? ja : en)
  const currentUser = getAuthUser()
  const [avatarSeed] = useState<number>(() => ensureAvatarSeed())

  const userRoleLabel = currentUser?.role
    ? (roleLabels[language]?.[currentUser.role as keyof typeof roleLabels['zh-CN']] || currentUser.role)
    : t.userRole

  const [name, setName] = useState(currentUser?.username || '')
  const [email, setEmail] = useState(currentUser?.email || '')
  const [phone, setPhone] = useState(currentUser?.phone || '')
  const [isSaving, setIsSaving] = useState(false)

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const isProfileComplete = Boolean(name.trim() && email.trim() && phone.trim())

  const profileMeta = useMemo(() => {
    const displayName = currentUser?.username || 'User'
    const displayEmail = currentUser?.email || t.placeholders.email
    const displayPhone = currentUser?.phone || t.placeholders.phone
    const userId = buildUserId(`${displayName}-${displayEmail}-${displayPhone}`)
    const preset = avatarPresets[avatarSeed % avatarPresets.length]
    const lastLoginAt = getLastLoginAt()
    const lastLoginText = lastLoginAt ? new Date(lastLoginAt).toLocaleString(language) : t.noRecord
    return { displayName, displayEmail, displayPhone, userId, preset, lastLoginText }
  }, [avatarSeed, currentUser, language, t.noRecord, t.placeholders.email, t.placeholders.phone])

  const handleSaveProfile = async (e: FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return toast.error(tr('用户名不能为空', 'Username is required', 'ユーザー名は必須です'))
    if (email.trim() && !/\S+@\S+\.\S+/.test(email.trim())) return toast.error(t.toast.emailInvalid)
    if (phone.trim() && !/^\d{11}$/.test(phone.trim())) return toast.error(t.toast.phoneInvalid)

    setIsSaving(true)
    try {
      await updateAuthUser({ username: name.trim(), email: email.trim(), phone: phone.trim() })
      toast.success(t.toast.profileUpdated)
    } catch (error: unknown) {
      const message = isAxiosError(error) ? error.response?.data?.detail : ''
      toast.error(typeof message === 'string' && message ? message : t.toast.notLoggedIn)
    } finally {
      setIsSaving(false)
    }
  }

  const handleChangePassword = async (e: FormEvent) => {
    e.preventDefault()
    if (!currentPassword || !newPassword || !confirmPassword) return toast.error(t.toast.passwordRequired)
    if (newPassword.length < 6) return toast.error(t.toast.passwordTooShort)
    if (newPassword !== confirmPassword) return toast.error(t.toast.passwordMismatch)

    try {
      await changePassword(currentPassword, newPassword)
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      toast.success(t.toast.passwordUpdated)
    } catch (error: unknown) {
      const message = isAxiosError(error) ? error.response?.data?.detail : ''
      toast.error(typeof message === 'string' && message ? message : t.toast.passwordRequired)
    }
  }

  return (
    <div className="space-y-5 h-full overflow-y-auto scrollbar-thin pb-4">
      <section className="glass overflow-hidden">
        <div className="h-1.5 bg-gradient-to-r from-primary-500 via-blue-400 to-cyan-300" />
        <div className="relative p-5 md:p-6">
          <div className="absolute right-5 top-4 text-xs text-slate-500">{t.recentLogin}: {profileMeta.lastLoginText}</div>
          <div className="mt-3 flex flex-wrap items-center gap-4">
            <div
              className="flex h-20 w-20 items-center justify-center rounded-full border border-white/70 text-3xl font-semibold text-white shadow-lg"
              style={{ background: `linear-gradient(135deg, ${profileMeta.preset.from}, ${profileMeta.preset.to})` }}
              title="Random Avatar"
            >
              <span>{profileMeta.preset.icon}</span>
            </div>

            <div className="min-w-[240px]">
              <h3 className="text-2xl font-semibold text-slate-900">{profileMeta.displayName}</h3>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs" style={{ backgroundColor: 'color-mix(in srgb, var(--theme-primary) 16%, transparent)', color: 'var(--theme-body-text)' }}>
                  <BadgeCheck className="h-3.5 w-3.5" />
                  {userRoleLabel}
                </span>
                <span className="rounded-full px-2.5 py-1 text-xs" style={{ backgroundColor: 'color-mix(in srgb, var(--theme-primary) 12%, transparent)', color: 'var(--theme-body-text)' }}>
                  {t.userId}: {profileMeta.userId}
                </span>
              </div>
              <div className="mt-3 grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
                <p className="inline-flex items-center gap-1.5 text-slate-700"><Mail className="h-4 w-4" />{profileMeta.displayEmail}</p>
                <p className="inline-flex items-center gap-1.5 text-slate-700"><Phone className="h-4 w-4" />{profileMeta.displayPhone}</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <section className="glass rounded-xl p-5 xl:col-span-7">
          <h4 className="text-base font-semibold text-slate-900">{t.editProfile}</h4>
          <p className="mt-1 text-xs text-slate-500">{t.editProfileHint}</p>
          <form className="mt-4 space-y-4" onSubmit={handleSaveProfile}>
            <label className="block">
              <span className="mb-2 block text-sm text-slate-700">{tr('用户名', 'Username', 'ユーザー名')}</span>
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder={tr('请输入用户名', 'Enter username', 'ユーザー名を入力')} />
            </label>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <label className="block">
                <span className="mb-2 block text-sm text-slate-700">{t.email}</span>
                <input className="input" value={email} onChange={(e) => setEmail(e.target.value)} placeholder={t.placeholders.email} />
              </label>
              <label className="block">
                <span className="mb-2 block text-sm text-slate-700">{t.phone}</span>
                <input className="input" value={phone} onChange={(e) => setPhone(e.target.value.replace(/\D/g, '').slice(0, 11))} placeholder={t.placeholders.phone} />
              </label>
            </div>

            <button type="submit" title={t.save} className="btn-primary px-4 py-2" disabled={isSaving}>
              <Save className="h-4 w-4" />
              {isSaving ? t.saving : t.save}
            </button>
          </form>
        </section>

        <section className="glass rounded-xl p-5 xl:col-span-5">
          <h4 className="text-base font-semibold text-slate-900">{t.accountInfo}</h4>
          <div className="mt-4 space-y-2 text-sm">
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
              <p className="text-xs text-slate-500">{t.accountType}</p>
              <p className="mt-1 text-slate-800">{userRoleLabel}</p>
            </div>
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
              <p className="text-xs text-slate-500">{t.userId}</p>
              <p className="mt-1 text-slate-800">{profileMeta.userId}</p>
            </div>
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
              <p className="text-xs text-slate-500">{t.status}</p>
              <p className={`mt-1 ${isProfileComplete ? 'text-emerald-700' : 'text-amber-700'}`}>
                {isProfileComplete ? tr('已完善', 'Completed', '完了') : tr('未完善', 'Incomplete', '未完了')}
              </p>
            </div>
          </div>
        </section>
      </div>

      <section className="glass rounded-xl p-5">
        <h4 className="text-base font-semibold text-slate-900">{t.changePassword}</h4>
        <form className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2" onSubmit={handleChangePassword}>
          <label className="block md:col-span-2">
            <span className="mb-2 block text-sm text-slate-700">{t.currentPassword}</span>
            <div className="relative">
              <KeyRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input className="input pl-10" type="password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} placeholder={t.placeholders.currentPassword} />
            </div>
          </label>

          <label className="block">
            <span className="mb-2 block text-sm text-slate-700">{t.newPassword}</span>
            <div className="relative">
              <Shield className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input className="input pl-10" type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} placeholder={t.placeholders.newPassword} />
            </div>
          </label>

          <label className="block">
            <span className="mb-2 block text-sm text-slate-700">{t.confirmPassword}</span>
            <div className="relative">
              <Shield className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input className="input pl-10" type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} placeholder={t.placeholders.confirmPassword} />
            </div>
          </label>

          <div className="mt-1 flex items-center justify-between gap-3 md:col-span-2">
            <p className="text-xs text-slate-500">{t.passwordTip}</p>
            <button type="submit" title={t.updatePassword} className="btn-secondary px-4 py-2 text-xs shrink-0">{t.updatePassword}</button>
          </div>
        </form>
      </section>
    </div>
  )
}
