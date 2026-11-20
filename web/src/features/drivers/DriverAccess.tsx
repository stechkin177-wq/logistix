import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { Banner } from '../../shared/ui/Banner'
import { TextField } from '../../shared/ui/TextField'
import { WriteButton } from '../../shared/ui/WriteButton'
import { useGrantDriverAccess, useRevokeDriverAccess } from './hooks'
import type { Driver } from './types'

/** Доступ водителя в мобильную версию: телефон из карточки + пароль, который задаёт офис. */
export function DriverAccess({ driver }: { driver: Driver }) {
  const { t } = useTranslation()
  const grant = useGrantDriverAccess()
  const revoke = useRevokeDriverAccess()
  const [password, setPassword] = useState('')
  const [granted, setGranted] = useState<string | null>(null)
  const [revoked, setRevoked] = useState(false)
  const has = (driver.user !== null && !revoked) || granted !== null
  return (
    <section className="mt-4 space-y-2 border-t border-line pt-3" aria-label={t('driver.grant.title')}>
      <h3 className="text-sm font-semibold">{t('driver.grant.title')}</h3>
      {grant.isError ? <Banner kind="error">{errorMessage(grant.error, t)}</Banner> : null}
      {revoke.isError ? <Banner kind="error">{errorMessage(revoke.error, t)}</Banner> : null}
      {granted ? <Banner kind="info">{t('driver.grant.granted', { login: granted })}</Banner> : null}
      {has ? (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-sm text-muted">{t('driver.grant.has')}</span>
          <WriteButton permission="drivers.update" variant="dangerSoft" disabled={revoke.isPending} onClick={() => { revoke.mutate(driver.id, { onSuccess: () => { setRevoked(true); setGranted(null) } }) }}>
            {t('driver.grant.revoke')}
          </WriteButton>
        </div>
      ) : (
        <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); grant.mutate({ id: driver.id, password }, { onSuccess: (r) => { setGranted(r.login); setRevoked(false); setPassword('') } }) }}>
          <p className="text-xs text-muted">{t('driver.grant.text')}</p>
          <TextField label={t('driver.grant.password')} type="password" autoComplete="new-password" value={password} onChange={(e) => { setPassword(e.target.value) }} />
          <WriteButton type="submit" permission="drivers.update" variant="primary" disabled={grant.isPending || password === ''}>{t('driver.grant.give')}</WriteButton>
        </form>
      )}
    </section>
  )
}
