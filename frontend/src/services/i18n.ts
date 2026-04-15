export type LanguageCode = 'zh-CN' | 'en-US' | 'ja-JP'

export const I18N_CHANGED_EVENT = 'docfusion-i18n-changed'
const LANGUAGE_KEY = 'docfusion_language'

const supportedLanguages: LanguageCode[] = ['zh-CN', 'en-US', 'ja-JP']

export const getStoredLanguage = (): LanguageCode => {
  const raw = localStorage.getItem(LANGUAGE_KEY) as LanguageCode | null
  if (raw && supportedLanguages.includes(raw)) return raw
  return 'zh-CN'
}

export const setLanguage = (language: LanguageCode) => {
  localStorage.setItem(LANGUAGE_KEY, language)
  window.dispatchEvent(new Event(I18N_CHANGED_EVENT))
}

export const languageLabelMap: Record<LanguageCode, string> = {
  'zh-CN': '简体中文',
  'en-US': 'English',
  'ja-JP': '日本語',
}

export const profileI18n = {
  'zh-CN': {
    recentLogin: '最近登录',
    noRecord: '暂无记录',
    userRole: '普通用户',
    editProfile: '修改个人信息',
    editProfileHint: '请确保邮箱与手机号准确无误，便于接收系统通知。',
    name: '姓名',
    email: '邮箱',
    phone: '手机号',
    save: '保存信息',
    saving: '保存中...',
    accountInfo: '账号信息',
    accountType: '账号类型',
    userId: '用户编号',
    status: '资料状态',
    completed: '已完善',
    changePassword: '修改密码',
    currentPassword: '当前密码',
    newPassword: '新密码',
    confirmPassword: '确认新密码',
    passwordTip: '密码修改将同步到后端账号系统，请妥善保管。',
    updatePassword: '更新密码',
    placeholders: {
      name: '请输入姓名',
      email: 'name@company.com',
      phone: '11位手机号',
      currentPassword: '请输入当前密码',
      newPassword: '至少6位',
      confirmPassword: '再次输入新密码',
    },
    toast: {
      nameRequired: '姓名不能为空',
      emailInvalid: '邮箱格式不正确',
      phoneInvalid: '手机号需为11位数字',
      notLoggedIn: '当前未登录，无法保存',
      profileUpdated: '个人信息已更新',
      passwordRequired: '请完整填写密码信息',
      passwordTooShort: '新密码至少6位',
      passwordMismatch: '两次新密码不一致',
      passwordUpdated: '密码已更新',
    },
  },
  'en-US': {
    recentLogin: 'Last login',
    noRecord: 'No record',
    userRole: 'Standard User',
    editProfile: 'Edit Profile',
    editProfileHint: 'Keep your email and phone accurate for system notifications.',
    name: 'Name',
    email: 'Email',
    phone: 'Phone',
    save: 'Save',
    saving: 'Saving...',
    accountInfo: 'Account Info',
    accountType: 'Account Type',
    userId: 'User ID',
    status: 'Profile Status',
    completed: 'Completed',
    changePassword: 'Change Password',
    currentPassword: 'Current Password',
    newPassword: 'New Password',
    confirmPassword: 'Confirm Password',
    passwordTip: 'Password updates are synced to the backend account system.',
    updatePassword: 'Update Password',
    placeholders: {
      name: 'Enter your name',
      email: 'name@company.com',
      phone: '11-digit phone',
      currentPassword: 'Enter current password',
      newPassword: 'At least 6 chars',
      confirmPassword: 'Enter new password again',
    },
    toast: {
      nameRequired: 'Name is required',
      emailInvalid: 'Invalid email format',
      phoneInvalid: 'Phone must be 11 digits',
      notLoggedIn: 'Not logged in, unable to save',
      profileUpdated: 'Profile updated',
      passwordRequired: 'Please fill password fields',
      passwordTooShort: 'New password must be at least 6 chars',
      passwordMismatch: 'Passwords do not match',
      passwordUpdated: 'Password updated',
    },
  },
  'ja-JP': {
    recentLogin: '最近のログイン',
    noRecord: '記録なし',
    userRole: '一般ユーザー',
    editProfile: 'プロフィール編集',
    editProfileHint: '通知を受け取るため、メールアドレスと電話番号を正確に入力してください。',
    name: '氏名',
    email: 'メール',
    phone: '電話番号',
    save: '保存',
    saving: '保存中...',
    accountInfo: 'アカウント情報',
    accountType: 'アカウント種別',
    userId: 'ユーザーID',
    status: 'プロフィール状態',
    completed: '完了',
    changePassword: 'パスワード変更',
    currentPassword: '現在のパスワード',
    newPassword: '新しいパスワード',
    confirmPassword: '新しいパスワード確認',
    passwordTip: 'パスワード変更はバックエンドのアカウントシステムに同期されます。',
    updatePassword: 'パスワード更新',
    placeholders: {
      name: '氏名を入力',
      email: 'name@company.com',
      phone: '11桁の電話番号',
      currentPassword: '現在のパスワード',
      newPassword: '6文字以上',
      confirmPassword: '新しいパスワードを再入力',
    },
    toast: {
      nameRequired: '氏名は必須です',
      emailInvalid: 'メール形式が正しくありません',
      phoneInvalid: '電話番号は11桁で入力してください',
      notLoggedIn: 'ログインしていないため保存できません',
      profileUpdated: 'プロフィールを更新しました',
      passwordRequired: 'パスワード項目を入力してください',
      passwordTooShort: '新しいパスワードは6文字以上必要です',
      passwordMismatch: 'パスワードが一致しません',
      passwordUpdated: 'パスワードを更新しました',
    },
  },
} as const

export const sidebarI18n = {
  'zh-CN': {
    dashboard: '仪表盘',
    documents: '文档管理',
    operation: '文档智能操作',
    tableFill: '表格填写',
    knowledge: '知识图谱',
    workLog: '工作日志',
    systemName: '知融云枢',
    systemSub: '文档智能融合系统',
  },
  'en-US': {
    dashboard: 'Dashboard',
    documents: 'Documents',
    operation: 'Doc Operations',
    tableFill: 'Table Fill',
    knowledge: 'Knowledge Graph',
    workLog: 'Work Log',
    systemName: 'ZhiRong Hub',
    systemSub: 'Smart Document Fusion',
  },
  'ja-JP': {
    dashboard: 'ダッシュボード',
    documents: 'ドキュメント管理',
    operation: 'ドキュメント操作',
    tableFill: '表入力',
    knowledge: 'ナレッジグラフ',
    workLog: '作業ログ',
    systemName: '知融云枢',
    systemSub: '文書インテリジェント融合',
  },
} as const
