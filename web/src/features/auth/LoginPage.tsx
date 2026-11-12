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
import { TotpStep } from './TotpStep'

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
  const { login, completeTotp, context, hasTokens } = useAuth()
  const { status } = useSession()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const branding = useBranding()
  const [loginValue, setLoginValue] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({})
  const [totp, setTotp] = useState<{ challenge: string; setup: boolean } | null>(null)

  const target = safeRedirect(params.get('next'))
  if (hasTokens && context === 'platform' && !busy) return <Navigate to="/platform" replace />
  if (status === 'authenticated' && !busy) return <Navigate to={target} replace />

  const submit = async (event: SyntheticEvent) => {
    event.preventDefault()
    setBusy(true)
    setFormError(null)
    setFieldErrors({})
    try {
      const result = await login(loginValue.trim(), password)
      if (result.kind === 'totp') {
        setPassword('') // пароль больше не нужен; дальше только код
        setTotp({ challenge: result.challenge, setup: result.setup })
        return
      }
      // платформенная роль -> Центр управления; остальные -> компания (или страница из ?next=)
      void navigate(result.context === 'platform' ? '/platform' : target, { replace: true })
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

  const header = (
    <div className="flex items-center gap-2.5">
      {branding.logo_url ? (
        <img src={branding.logo_url} alt="" className="size-9 rounded-md object-contain" />
      ) : (
        <span aria-hidden="true" className="inline-flex size-9 items-center justify-center rounded-md bg-brand-600 text-sm font-bold text-brand-fg">
          {branding.app_name.charAt(0).toUpperCase()}
        </span>
      )}
      <h1 className="text-lg font-semibold">{branding.app_name}</h1>
    </div>
  )
  const card = 'w-full max-w-sm space-y-4 rounded-card border border-line bg-surface p-7 shadow-pop'

  return (
    <div className="flex min-h-dvh items-center justify-center bg-canvas p-4">
      {totp ? (
        <div className={card}>
          {header}
          <TotpStep
            challenge={totp.challenge}
            setup={totp.setup}
            onSubmit={async (code) => {
              await completeTotp(totp.challenge, code)
              void navigate('/platform', { replace: true })
            }}
            onExpired={() => { setTotp(null); setFormError(t('auth.totpExpired')) }}
          />
        </div>
      ) : (
        <form onSubmit={(event) => void submit(event)} className={card} noValidate>
          {header}
          <p className="text-sm text-muted">{t('auth.title')}</p>
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
      )}
    </div>
  )
}
