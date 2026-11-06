import { useState, type SyntheticEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, useNavigate, useSearchParams } from 'react-router'
import { ApiError } from '../../shared/api/errors'
import { safeRedirect } from '../../shared/auth/redirect'
import { useAuth } from '../../shared/auth/useAuth'
import { useSession } from '../../shared/auth/useSession'
import { useBranding } from '../../shared/branding/useBranding'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { Input } from '../../shared/ui/Input'

function loginErrorKey(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 'network_error') return 'errors.network'
    if (error.status === 401) return 'auth.invalidCredentials'
    if (error.status === 429) return 'errors.tooMany'
    if (error.status >= 500) return 'errors.server'
    if (error.status === 403) return 'auth.noCompany'
  }
  return 'errors.unknown'
}

export function LoginPage() {
  const { t } = useTranslation()
  const { login } = useAuth()
  const { status } = useSession()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const branding = useBranding()
  const [loginValue, setLoginValue] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({})

  const target = safeRedirect(params.get('next'))
  if (status === 'authenticated' && !busy) return <Navigate to={target} replace />

  const submit = async (event: SyntheticEvent) => {
    event.preventDefault()
    setBusy(true)
    setFormError(null)
    setFieldErrors({})
    try {
      await login(loginValue.trim(), password)
      void navigate(target, { replace: true })
    } catch (error) {
      // subscription_blocked обрабатывает AuthProvider (экран «Доступ приостановлен»)
      if (error instanceof ApiError && error.code === 'subscription_blocked') return
      if (error instanceof ApiError && error.status === 400 && Object.keys(error.fields).length > 0) {
        setFieldErrors(error.fields)
      } else {
        setFormError(t(loginErrorKey(error)))
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 p-4 dark:bg-slate-950">
      <form
        onSubmit={(event) => void submit(event)}
        className="w-full max-w-sm space-y-3 rounded border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900"
        noValidate
      >
        <div className="flex items-center gap-2">
          {branding.logo_url ? (
            <img src={branding.logo_url} alt="" className="size-8 rounded object-contain" />
          ) : null}
          <h1 className="text-lg font-semibold">{branding.app_name}</h1>
        </div>
        <p className="text-sm text-slate-500">{t('auth.title')}</p>
        {formError ? <Banner kind="error">{formError}</Banner> : null}
        <Input
          label={t('auth.login')}
          name="login"
          autoComplete="username"
          autoFocus
          value={loginValue}
          error={fieldErrors.login?.join(' ')}
          onChange={(event) => {
            setLoginValue(event.target.value)
          }}
        />
        <Input
          label={t('auth.password')}
          name="password"
          type="password"
          autoComplete="current-password"
          value={password}
          error={fieldErrors.password?.join(' ')}
          onChange={(event) => {
            setPassword(event.target.value)
          }}
        />
        <Button type="submit" variant="primary" className="w-full" disabled={busy || !loginValue || !password}>
          {busy ? t('common.loading') : t('auth.submit')}
        </Button>
      </form>
    </div>
  )
}
