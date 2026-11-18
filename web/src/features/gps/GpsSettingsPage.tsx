import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { useFormat } from '../../shared/format/useFormat'
import { Banner } from '../../shared/ui/Banner'
import { Card, CardHeader } from '../../shared/ui/Card'
import { Checkbox } from '../../shared/ui/Checkbox'
import { PageHeader } from '../../shared/ui/PageHeader'
import { Spinner } from '../../shared/ui/Spinner'
import { TextField } from '../../shared/ui/TextField'
import { WriteButton } from '../../shared/ui/WriteButton'
import { MapPin } from '../../shared/ui/icons'
import { useGpsAccount, useSaveGpsAccount, useSyncGps, useTestGpsAccount } from './hooks'
import type { GpsAccount } from './types'

const DEFAULT_URL = 'https://hst-api.wialon.com'

function AccountForm({ account }: { account: GpsAccount }) {
  const { t } = useTranslation()
  const { dateTime } = useFormat()
  const save = useSaveGpsAccount()
  const test = useTestGpsAccount()
  const sync = useSyncGps()
  const [form, setForm] = useState({ token: '', base_url: account.base_url ?? DEFAULT_URL, is_active: account.is_active ?? true })
  const webhook = account.webhook_path ?? ''
  return (
    <Card>
      <CardHeader title={t('gps.accountTitle')} />
      <form className="grid gap-3 p-4 sm:grid-cols-2" noValidate onSubmit={(e) => { e.preventDefault(); save.mutate(form) }}>
        <TextField
          label={t('gps.token')}
          type="password"
          autoComplete="new-password"
          value={form.token}
          onChange={(e) => { setForm({ ...form, token: e.target.value }) }}
          hint={account.has_token ? t('gps.tokenKept') : t('gps.tokenHint')}
        />
        <TextField label={t('gps.baseUrl')} value={form.base_url} onChange={(e) => { setForm({ ...form, base_url: e.target.value }) }} hint={t('gps.baseUrlHint')} />
        <Checkbox className="self-end" label={t('gps.accountActive')} checked={form.is_active} onChange={(e) => { setForm({ ...form, is_active: e.target.checked }) }} />
        <div className="space-y-2 sm:col-span-2">
          {save.isError ? <Banner kind="error">{errorMessage(save.error, t)}</Banner> : null}
          {save.isSuccess ? <Banner kind="info">{t('gps.saved')}</Banner> : null}
          {test.data ? <Banner kind={test.data.ok ? 'info' : 'error'}>{test.data.ok ? t('gps.testOk', { units: test.data.units ?? 0 }) : (test.data.error ?? '')}</Banner> : null}
          {test.isError ? <Banner kind="error">{errorMessage(test.error, t)}</Banner> : null}
          {sync.data ? <Banner kind={sync.data.ok ? 'info' : 'error'}>{sync.data.ok ? t('gps.synced', { units: sync.data.units?.units_seen ?? 0 }) : (sync.data.error ?? '')}</Banner> : null}
          {sync.isError ? <Banner kind="error">{errorMessage(sync.error, t)}</Banner> : null}
          {account.last_sync_error ? <Banner kind="error">{t('gps.lastError', { error: account.last_sync_error })}</Banner> : null}
          {account.last_synced_at ? <p className="text-xs text-muted">{t('gps.lastSynced', { when: dateTime(account.last_synced_at) })}</p> : null}
          <div className="flex flex-wrap gap-2">
            <WriteButton type="submit" permission="gps.manage" variant="primary" disabled={save.isPending || (!account.has_token && !form.token.trim())}>
              {save.isPending ? t('common.saving') : t('common.save')}
            </WriteButton>
            <WriteButton permission="gps.manage" disabled={!account.has_token || test.isPending} onClick={() => { test.mutate() }}>{test.isPending ? t('gps.testing') : t('gps.test')}</WriteButton>
            <WriteButton permission="gps.manage" disabled={!account.has_token || sync.isPending} onClick={() => { sync.mutate() }}>{sync.isPending ? t('gps.syncing') : t('gps.sync')}</WriteButton>
          </div>
        </div>
      </form>
      {webhook ? (
        <div className="space-y-1 border-t border-line p-4">
          <h3 className="text-sm font-semibold">{t('gps.webhookTitle')}</h3>
          <p className="text-xs text-muted">{t('gps.webhookHint')}</p>
          <code className="block break-all rounded-control bg-surface-2 px-2 py-1.5 text-xs">{`https://<${t('gps.apiAddress')}>${webhook}?event=enter&unit=%UNIT%&zone=%ZONE%`}</code>
        </div>
      ) : null}
    </Card>
  )
}

/** Настройки GPS: токен Wialon компании (хранится зашифрованным), проверка подключения, синхронизация, адрес вебхука. */
export function GpsSettingsPage() {
  const { t } = useTranslation()
  const account = useGpsAccount()
  return (
    <div className="space-y-3">
      <PageHeader icon={MapPin} title={t('gps.settingsTitle')} />
      {account.isPending ? <Spinner /> : null}
      {account.isError ? <Banner kind="error">{errorMessage(account.error, t)}</Banner> : null}
      {account.data ? <AccountForm key={account.data.configured ? 'on' : 'off'} account={account.data} /> : null}
    </div>
  )
}
