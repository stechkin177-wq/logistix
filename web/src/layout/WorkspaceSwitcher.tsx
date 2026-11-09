import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ApiError, errorMessage } from '../shared/api/errors'
import { useAuth } from '../shared/auth/useAuth'
import { Banner } from '../shared/ui/Banner'
import { Button } from '../shared/ui/Button'
import { Dialog } from '../shared/ui/Dialog'
import { Select } from '../shared/ui/Select'
import { TextField } from '../shared/ui/TextField'
import { pushToast } from '../shared/ui/toast'

interface Props {
  /** Где пользователь сейчас: в своей компании или в Центре управления платформы. */
  mode: 'company' | 'platform'
  /** Компании аккаунта (нужны в платформенном режиме для перехода в «Администратор компании»). */
  companies: { id: number; name: string }[]
  /** Владельцу при переходе в платформу нужен свежий код TOTP. */
  needsCode?: boolean
}

/**
 * Переключатель рабочих пространств одного аккаунта: «Владелец платформы» / «Администратор компании».
 * Использует существующие переходы контекста (switch-company): права, токены и данные контекстов остаются
 * раздельными, из компании в платформу - только со свежим кодом TOTP. Вид - только у аккаунтов с платформенной ролью.
 */
export function WorkspaceSwitcher({ mode, companies, needsCode = false }: Props) {
  const { t } = useTranslation()
  const { switchToPlatform, switchCompany } = useAuth()
  const [busy, setBusy] = useState(false)
  const [asking, setAsking] = useState(false)
  const [code, setCode] = useState('')
  const [error, setError] = useState<string>()

  const toCompany = (id: number) => {
    setBusy(true)
    switchCompany(id)
      .catch((e: unknown) => { pushToast('error', errorMessage(e, t)) })
      .finally(() => { setBusy(false) })
  }
  const toPlatform = (value?: string) => {
    setBusy(true)
    setError(undefined)
    switchToPlatform(value)
      .then(() => { setAsking(false) })
      .catch((e: unknown) => {
        if (needsCode) setError(e instanceof ApiError && e.code === 'totp_invalid' ? t('auth.totpInvalid') : errorMessage(e, t))
        else pushToast('error', errorMessage(e, t))
      })
      .finally(() => { setBusy(false) })
  }

  const seg = (active: boolean) =>
    `flex-1 rounded px-2 py-1 text-xs ${active ? 'bg-brand-600 font-medium text-brand-fg' : 'text-slate-700 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'} disabled:opacity-50`
  const single = companies.length === 1 ? companies[0] : undefined

  return (
    <div className="space-y-1">
      <div role="group" aria-label={t('workspace.title')} className="flex gap-1 rounded border border-slate-300 p-0.5 dark:border-slate-600">
        <button
          type="button"
          aria-pressed={mode === 'platform'}
          disabled={busy || mode === 'platform'}
          className={seg(mode === 'platform')}
          onClick={() => { if (needsCode) { setCode(''); setError(undefined); setAsking(true) } else toPlatform() }}
        >
          {t('workspace.owner')}
        </button>
        <button
          type="button"
          aria-pressed={mode === 'company'}
          disabled={busy || mode === 'company' || companies.length === 0}
          title={mode === 'platform' && companies.length === 0 ? t('workspace.noCompany') : undefined}
          className={seg(mode === 'company')}
          onClick={() => { if (single) toCompany(single.id) }}
        >
          {t('workspace.admin')}
        </button>
      </div>
      {mode === 'platform' && companies.length > 1 ? (
        <Select
          label={t('platformShell.openCompany')}
          hideLabel
          value=""
          disabled={busy}
          placeholder={t('platformShell.openCompany')}
          options={companies.map((c) => ({ value: String(c.id), label: c.name }))}
          onChange={(v) => { const id = Number(v); if (Number.isInteger(id) && id > 0) toCompany(id) }}
        />
      ) : null}
      <Dialog
        open={asking}
        title={t('workspace.owner')}
        onClose={() => { setAsking(false) }}
        busy={busy}
        footer={
          <>
            <Button onClick={() => { setAsking(false) }} disabled={busy}>{t('common.cancel')}</Button>
            <Button variant="primary" disabled={busy || code.trim().length < 6} onClick={() => { toPlatform(code.trim()) }}>{t('auth.totpSubmit')}</Button>
          </>
        }
      >
        <div className="space-y-3">
          {error ? <Banner kind="error">{error}</Banner> : null}
          <p className="text-sm">{t('platformShell.codeHint')}</p>
          <TextField label={t('auth.totpCode')} inputMode="numeric" autoComplete="one-time-code" maxLength={7} value={code} onChange={(e) => { setCode(e.target.value) }} />
        </div>
      </Dialog>
    </div>
  )
}
