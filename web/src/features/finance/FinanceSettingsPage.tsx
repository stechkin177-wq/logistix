import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { useFormat } from '../../shared/format/useFormat'
import { useHandbookValues } from '../../shared/handbooks/useHandbook'
import { Badge } from '../../shared/ui/Badge'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { Checkbox } from '../../shared/ui/Checkbox'
import { DateTime } from '../../shared/ui/DateTime'
import { Select } from '../../shared/ui/Select'
import { Spinner } from '../../shared/ui/Spinner'
import { TextField } from '../../shared/ui/TextField'
import { WriteButton } from '../../shared/ui/WriteButton'
import { FieldsDialog } from './FieldsDialog'
import {
  useClosePeriod, useFinanceSettings, useMapStatus, useMigration, usePatchFinanceSettings, usePeriods,
  useReopenPeriod, useResolveIssue, useStatusMapping,
} from './ledgerHooks'
import type { FinanceSettings, MigrationIssue, PeriodRow } from './ledgerTypes'
import { PageHeader } from '../../shared/ui/PageHeader'
import { SlidersHorizontal } from '../../shared/ui/icons'

const BASE_CODES = ['KZT', 'RUB', 'USD', 'EUR']

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id} className="space-y-2 rounded-control border border-line p-3">
      <h2 id={id} className="text-sm font-semibold">{title}</h2>
      {children}
    </section>
  )
}

function BaseCurrency({ settings }: { settings: FinanceSettings }) {
  const { t } = useTranslation()
  const currencies = useHandbookValues('currency', { activeOnly: true })
  const patch = usePatchFinanceSettings()
  const [value, setValue] = useState('')
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | undefined>()
  const options = currencies.values.filter((v) => BASE_CODES.includes(v.code)).map((v) => ({ value: String(v.id), label: v.code }))
  const submit = () => {
    if (patch.isPending) return
    setError(undefined)
    patch.mutate({ base_currency: Number(value), reason: reason.trim() }, {
      onSuccess: () => { setValue(''); setReason('') },
      onError: (e) => { setError(errorMessage(e, t)) },
    })
  }
  return (
    <Section id="fs-currency" title={t('finance.settings.baseCurrency')}>
      <p className="text-sm">{t('finance.settings.currentBase')}: <b>{settings.base_currency?.code ?? '—'}</b></p>
      <p className="text-xs text-muted">{t('finance.settings.baseCurrencyHint')}</p>
      {error ? <Banner kind="error">{error}</Banner> : null}
      <div className="flex flex-wrap items-end gap-2">
        <Select label={t('finance.settings.newBase')} options={options} value={value} onChange={setValue} placeholder="—" />
        <TextField label={t('finance.ledger.reason')} value={reason} onChange={(e) => { setReason(e.target.value) }} />
        <WriteButton variant="primary" permission="finance.manage_settings" disabled={patch.isPending || !value || !reason.trim()} onClick={submit}>
          {t('finance.settings.changeBase')}
        </WriteButton>
      </div>
    </Section>
  )
}

function Flags({ settings }: { settings: FinanceSettings }) {
  const { t } = useTranslation()
  const patch = usePatchFinanceSettings()
  const [error, setError] = useState<string | undefined>()
  const save = (body: Record<string, unknown>) => {
    setError(undefined)
    patch.mutate(body, { onError: (e) => { setError(errorMessage(e, t)) } })
  }
  return (
    <Section id="fs-flags" title={t('finance.settings.flags')}>
      {error ? <Banner kind="error">{error}</Banner> : null}
      <div className="flex flex-col gap-1">
        <Checkbox
          label={t('finance.settings.allowBackdating')}
          checked={settings.allow_backdating}
          disabled={patch.isPending}
          onChange={(e) => { save({ allow_backdating: e.target.checked }) }}
        />
        <Checkbox
          label={t('finance.settings.syncCarrierPrice')}
          checked={settings.sync_carrier_price}
          disabled={patch.isPending}
          onChange={(e) => { save({ sync_carrier_price: e.target.checked }) }}
        />
        <Select
          label={t('finance.settings.expenseMode')}
          value={settings.expense_creation_mode}
          disabled={patch.isPending}
          onChange={(value) => { save({ expense_creation_mode: value }) }}
          options={[
            { value: 'manual', label: t('finance.settings.modeManual') },
            { value: 'on_assign', label: t('finance.settings.modeOnAssign') },
          ]}
        />
      </div>
    </Section>
  )
}

function StatusMapping() {
  const { t } = useTranslation()
  const query = useStatusMapping()
  const map = useMapStatus()
  const [pick, setPick] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | undefined>()
  if (query.isError) return <Banner kind="error">{errorMessage(query.error, t)}</Banner>
  if (!query.data) return <Spinner />
  const d = query.data
  const assign = (code: string) => {
    const value = Number(pick[code])
    if (!value || map.isPending) return
    setError(undefined)
    map.mutate({ value, code }, { onError: (e) => { setError(errorMessage(e, t)) } })
  }
  return (
    <Section id="fs-status" title={t('finance.settings.statusMapping')}>
      <p className="text-xs text-muted">{t('finance.settings.statusMappingHint')}</p>
      {error ? <Banner kind="error">{error}</Banner> : null}
      {d.switch_blocked ? (
        <Banner kind="warning">
          {t('finance.settings.switchBlocked')}
          <ul className="list-disc pl-5">{d.blockers.map((b) => <li key={b.code}>{b.message}</li>)}</ul>
        </Banner>
      ) : <Badge tone="success">{t('finance.settings.mapped')}</Badge>}
      <p className="text-sm">
        {t('finance.settings.completedStatus')}: <b>{d.completed_status ? `${d.completed_status.name} (${d.completed_status.code})` : '—'}</b>
      </p>
      <ul className="text-sm">
        {d.values.map((v) => (
          <li key={v.id}>{v.name} - {v.code || t('finance.settings.noCode')}{v.is_active ? '' : ` (${t('common.inactive')})`}</li>
        ))}
      </ul>
      {d.unmapped.map((u) => (
        <div key={u.code} className="flex flex-wrap items-end gap-2">
          <span className="text-sm">{t('finance.settings.assignCode', { code: u.code })}</span>
          <Select
            label={t('finance.settings.statusValue')}
            hideLabel
            value={pick[u.code] ?? ''}
            onChange={(value) => { setPick((x) => ({ ...x, [u.code]: value })) }}
            placeholder="—"
            options={d.values.filter((v) => !v.code && v.is_active).map((v) => ({ value: String(v.id), label: v.name }))}
          />
          <WriteButton permission="finance.manage_settings" disabled={map.isPending || !pick[u.code]} onClick={() => { assign(u.code) }}>
            {t('finance.settings.assign')}
          </WriteButton>
        </div>
      ))}
    </Section>
  )
}

function Periods() {
  const { t } = useTranslation()
  const { dateTime } = useFormat()
  const query = usePeriods()
  const close = useClosePeriod()
  const reopen = useReopenPeriod()
  const [target, setTarget] = useState<'close' | PeriodRow | null>(null)
  if (query.isError) return <Banner kind="error">{errorMessage(query.error, t)}</Banner>
  if (!query.data) return <Spinner />
  return (
    <Section id="fs-periods" title={t('finance.settings.periods')}>
      <WriteButton permission="finance.close_period" onClick={() => { setTarget('close') }}>{t('finance.settings.closeMonth')}</WriteButton>
      <ul className="divide-y divide-line text-sm">
        {query.data.map((p) => (
          <li key={p.id} className="flex flex-wrap items-center justify-between gap-2 py-1">
            <span>{String(p.month).padStart(2, '0')}.{p.year}</span>
            <span className="flex items-center gap-2">
              <Badge tone={p.status === 'closed' ? 'warning' : 'success'}>{t(`finance.settings.period.${p.status}`)}</Badge>
              {p.closed_at ? <span className="text-xs text-muted">{dateTime(p.closed_at)} {p.closed_by ?? ''}</span> : null}
              {p.status === 'closed' ? (
                <WriteButton permission="finance.reopen_period" onClick={() => { setTarget(p) }}>{t('finance.settings.reopen')}</WriteButton>
              ) : null}
            </span>
          </li>
        ))}
      </ul>
      {target === 'close' ? (
        <FieldsDialog
          title={t('finance.settings.closeMonth')}
          submitLabel={t('finance.settings.close')}
          permission="finance.close_period"
          onClose={() => { setTarget(null) }}
          fields={[
            { key: 'year', label: t('finance.settings.year'), type: 'decimal', required: true },
            { key: 'month', label: t('finance.settings.month'), type: 'decimal', required: true },
            { key: 'comment', label: t('finance.settings.comment') },
          ]}
          onSubmit={(v) => close.mutateAsync({ year: Number(v.year), month: Number(v.month), comment: v.comment ?? '' })}
        />
      ) : null}
      {target !== null && target !== 'close' ? (
        <FieldsDialog
          title={t('finance.settings.reopen')}
          submitLabel={t('finance.settings.reopen')}
          permission="finance.reopen_period"
          onClose={() => { setTarget(null) }}
          fields={[{ key: 'reason', label: t('finance.ledger.reason'), required: true }]}
          onSubmit={(v) => reopen.mutateAsync({ id: target.id, reason: v.reason ?? '' })}
        />
      ) : null}
    </Section>
  )
}

function Migration() {
  const { t } = useTranslation()
  const query = useMigration()
  const resolve = useResolveIssue()
  const [issue, setIssue] = useState<MigrationIssue | null>(null)
  if (query.isError) return <Banner kind="error">{errorMessage(query.error, t)}</Banner>
  if (!query.data) return <Spinner />
  const d = query.data
  const isTrip = issue?.issue_type === 'ambiguous_trip_expense'
  return (
    <Section id="fs-migration" title={t('finance.settings.migration')}>
      <p className="text-sm">{t('finance.settings.openIssues')}: <b>{d.open_count}</b></p>
      <ul className="text-sm">
        {d.runs.map((r) => (
          <li key={r.id}>
            {r.kind} / {r.mode} - {r.status} (<DateTime value={r.started_at} />)
            {r.unexplained !== null ? `, ${t('finance.settings.unexplained')}: ${String(r.unexplained)}` : ''}
            {r.not_reflected > 0 ? `, ${t('finance.settings.notReflected')}: ${String(r.not_reflected)}` : ''}
          </li>
        ))}
      </ul>
      <ul className="divide-y divide-line text-sm">
        {d.open_issues.map((i) => (
          <li key={i.id} className="flex flex-wrap items-center justify-between gap-2 py-1">
            <span>{i.message}</span>
            <Button onClick={() => { setIssue(i) }}>{t('finance.settings.resolve')}</Button>
          </li>
        ))}
      </ul>
      {issue ? (
        <FieldsDialog
          title={t('finance.settings.resolve')}
          submitLabel={t('finance.settings.resolve')}
          permission="finance.manage_settings"
          hint={isTrip ? t('finance.settings.resolveHint') : undefined}
          onClose={() => { setIssue(null) }}
          fields={[
            ...(isTrip
              ? [
                  {
                    key: 'resolution', label: t('finance.settings.resolution'), type: 'select' as const, required: true,
                    options: (['carrier_expense', 'manual_expense', 'justified_exclusion'] as const).map((r) => ({ value: r, label: t(`finance.settings.resolutions.${r}`) })),
                  },
                  { key: 'trip', label: t('finance.settings.resolutionTrip') },
                ]
              : []),
            { key: 'note', label: t('finance.settings.comment'), required: true },
          ]}
          onSubmit={(v) => resolve.mutateAsync({ id: issue.id, body: Object.fromEntries(Object.entries(v).filter(([, x]) => x !== '')) })}
        />
      ) : null}
    </Section>
  )
}

/** Настройки финансов (finance.manage_settings): валюта, флаги, статусы, месяцы, миграция. */
export function FinanceSettingsPage() {
  const { t } = useTranslation()
  const query = useFinanceSettings()
  if (query.isError) return <Banner kind="error">{errorMessage(query.error, t)}</Banner>
  if (!query.data) return <Spinner label={t('table.loading')} />
  const s = query.data
  return (
    <div className="space-y-3">
      <PageHeader icon={SlidersHorizontal} title={t('nav.financeSettings')} />
      <p className="text-sm">
        {t('finance.settings.engine')}: <Badge tone={s.engine === 'new' ? 'success' : 'info'}>{t(`finance.settings.engines.${s.engine}`)}</Badge>
        {s.financial_writes_frozen ? <> <Badge tone="danger">{t('finance.settings.frozen')}</Badge></> : null}
      </p>
      <BaseCurrency settings={s} />
      <Flags settings={s} />
      <StatusMapping />
      <Periods />
      <Migration />
    </div>
  )
}
