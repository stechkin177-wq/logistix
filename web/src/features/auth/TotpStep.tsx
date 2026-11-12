import { useEffect, useState, type SyntheticEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { ApiError } from '../../shared/api/errors'
import { api } from '../../shared/api/client'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { Input } from '../../shared/ui/Input'

interface Props {
  challenge: string
  /** Первое подключение: сначала показывается ключ для приложения-аутентификатора. */
  setup: boolean
  onSubmit: (code: string) => Promise<void>
  /** Талон истёк или недействителен: вернуться к вводу пароля. */
  onExpired: () => void
}

/** Второй шаг входа владельца платформы: код из приложения-аутентификатора (TOTP). */
export function TotpStep({ challenge, setup, onSubmit, onExpired }: Props) {
  const { t } = useTranslation()
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [key, setKey] = useState<{ secret: string; otpauth_uri: string } | null>(null)

  useEffect(() => {
    if (!setup) return
    api.post<{ secret: string; otpauth_uri: string }>('/auth/totp/setup/', { challenge }, { auth: false })
      .then(setKey)
      .catch(() => { setError(t('auth.totpExpired')) })
  }, [setup, challenge, t])

  const submit = async (event: SyntheticEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await onSubmit(code.trim())
    } catch (e) {
      if (e instanceof ApiError && e.code === 'totp_invalid') setError(t('auth.totpInvalid'))
      else if (e instanceof ApiError && e.status === 429) setError(t('errors.tooMany'))
      else if (e instanceof ApiError && e.status === 401) { onExpired(); return }
      else setError(t('errors.unknown'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted">{t(setup ? 'auth.totpSetupHint' : 'auth.totpHint')}</p>
      {setup && key ? (
        <div className="space-y-1 rounded-control border border-line p-2 text-sm">
          <p className="text-xs text-muted">{t('auth.totpKey')}</p>
          <p className="break-all font-mono" data-testid="totp-secret">{key.secret}</p>
          <p className="break-all text-xs text-muted">{key.otpauth_uri}</p>
        </div>
      ) : null}
      {error ? <Banner kind="error">{error}</Banner> : null}
      <form onSubmit={(event) => void submit(event)} className="space-y-3" noValidate>
        <Input
          label={t('auth.totpCode')}
          name="totp"
          inputMode="numeric"
          autoComplete="one-time-code"
          autoFocus
          maxLength={7}
          value={code}
          onChange={(event) => { setCode(event.target.value) }}
        />
        <Button type="submit" variant="primary" className="w-full" disabled={busy || code.trim().length < 6 || (setup && !key)}>
          {busy ? t('common.loading') : t('auth.totpSubmit')}
        </Button>
      </form>
    </div>
  )
}
