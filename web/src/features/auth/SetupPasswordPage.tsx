import { useState, type SyntheticEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router'
import { api } from '../../shared/api/client'
import { serverErrors } from '../../shared/forms/serverErrors'
import { useBranding } from '../../shared/branding/useBranding'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { Input } from '../../shared/ui/Input'

/** /setup-password?uid=..&token=..: человек сам задаёт пароль по одноразовой ссылке администратора сервера. */
export function SetupPasswordPage() {
  const { t } = useTranslation()
  const branding = useBranding()
  const [params] = useSearchParams()
  const uid = params.get('uid') ?? ''
  const token = params.get('token') ?? ''
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  const submit = async (event: SyntheticEvent) => {
    event.preventDefault()
    setError(null)
    if (password !== confirm) { setError(t('account.mismatch')); return }
    setBusy(true)
    try {
      await api.post('/auth/password-setup/', { uid, token, new_password: password }, { auth: false })
      setPassword('')
      setConfirm('')
      setDone(true)
    } catch (e) {
      const err = serverErrors(e, t)
      setError(err.fields.token ?? err.fields.new_password ?? err.banner ?? t('errors.unknown'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 p-4 dark:bg-slate-950">
      <div className="w-full max-w-sm space-y-3 rounded border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h1 className="text-lg font-semibold">{branding.app_name}</h1>
        {done ? (
          <>
            <Banner kind="info">{t('auth.setupDone')}</Banner>
            <Link to="/login" className="text-sm font-medium text-brand-700 hover:underline dark:text-brand-300">{t('auth.toLogin')}</Link>
          </>
        ) : !uid || !token ? (
          <Banner kind="error">{t('auth.setupInvalid')}</Banner>
        ) : (
          <form onSubmit={(event) => void submit(event)} className="space-y-3" noValidate>
            <p className="text-sm text-slate-500">{t('auth.setupHint')}</p>
            {error ? <Banner kind="error">{error}</Banner> : null}
            <Input label={t('account.newPassword')} name="new-password" type="password" autoComplete="new-password" autoFocus value={password} onChange={(e) => { setPassword(e.target.value) }} />
            <Input label={t('account.confirmPassword')} name="confirm-password" type="password" autoComplete="new-password" value={confirm} onChange={(e) => { setConfirm(e.target.value) }} />
            <Button type="submit" variant="primary" className="w-full" disabled={busy || !password || !confirm}>{busy ? t('common.loading') : t('auth.setupSubmit')}</Button>
          </form>
        )}
      </div>
    </div>
  )
}
