import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { useSession } from '../../shared/auth/useSession'
import { NO_ERRORS, serverErrors, type FormErrors } from '../../shared/forms/serverErrors'
import { useFocusInvalid } from '../../shared/forms/useFocusInvalid'
import { codecs, useUrlState } from '../../shared/hooks/useUrlState'
import { useHandbookValues } from '../../shared/handbooks/useHandbook'
import { Button } from '../../shared/ui/Button'
import { ConfirmDialog } from '../../shared/ui/ConfirmDialog'
import { DataTable, type Column } from '../../shared/ui/DataTable'
import { DateInput } from '../../shared/ui/DateInput'
import { DateTime } from '../../shared/ui/DateTime'
import { Drawer } from '../../shared/ui/Drawer'
import { EmptyState } from '../../shared/ui/EmptyState'
import { FormBanner } from '../../shared/ui/FormBanner'
import { PAGE_SIZES, Pagination } from '../../shared/ui/Pagination'
import { Select } from '../../shared/ui/Select'
import { TextField } from '../../shared/ui/TextField'
import { WriteButton } from '../../shared/ui/WriteButton'
import { useDeleteRate, useRates, useSaveRate } from './hooks'
import type { Rate } from './types'

const RATE_RE = /^\d{1,12}(\.\d{1,6})?$/
const KNOWN = /^(currency|date|rate)$/
const BASE_CURRENCY = 'KZT'

function RateDrawer({ rate, onClose }: { rate: Rate | null; onClose: () => void }) {
  const { t } = useTranslation()
  const currencies = useHandbookValues('currency', { activeOnly: true })
  const options = currencies.values.filter((v) => v.code !== BASE_CURRENCY)
  const [form, setForm] = useState({ currency: rate ? String(rate.currency.id) : '', date: rate?.date ?? '', rate: rate?.rate ?? '' })
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS)
  const save = useSaveRate()
  const ref = useRef<HTMLFormElement>(null)
  useFocusInvalid(ref, errors)

  const submit = () => {
    const local: Record<string, string> = {}
    if (!form.currency) local.currency = t('errors.requiredField')
    if (!form.date) local.date = t('errors.invalidDate')
    if (!RATE_RE.test(form.rate.trim())) local.rate = t('errors.invalidNumber')
    if (Object.keys(local).length > 0) {
      setErrors({ fields: local, banner: undefined })
      return
    }
    setErrors(NO_ERRORS)
    save.mutate(
      { id: rate?.id ?? null, body: { currency: Number(form.currency), date: form.date, rate: form.rate.trim() } },
      { onSuccess: onClose, onError: (error) => { setErrors(serverErrors(error, t, (p) => KNOWN.test(p))) } },
    )
  }
  const f = errors.fields
  return (
    <Drawer
      open
      title={rate ? t('finance.rates.edit') : t('finance.rates.add')}
      onClose={onClose}
      busy={save.isPending}
      footer={
        <>
          <Button onClick={onClose} disabled={save.isPending}>{t('common.cancel')}</Button>
          <WriteButton variant="primary" permission={rate ? 'finance.update' : 'finance.create'} disabled={save.isPending} onClick={submit}>
            {save.isPending ? t('common.saving') : t('common.save')}
          </WriteButton>
        </>
      }
    >
      <form ref={ref} noValidate onSubmit={(e) => { e.preventDefault(); submit() }} className="space-y-3">
        <FormBanner message={errors.banner} />
        <Select
          label={t('finance.rates.currency')}
          required
          value={form.currency}
          placeholder="—"
          options={options.map((v) => ({ value: String(v.id), label: `${v.code} — ${v.name}` }))}
          error={f.currency}
          onChange={(value) => { setForm((x) => ({ ...x, currency: value })) }}
        />
        <DateInput label={t('finance.rates.date')} required value={form.date} error={f.date} onChange={(value) => { setForm((x) => ({ ...x, date: value })) }} />
        <TextField label={t('finance.rates.rate')} required inputMode="decimal" value={form.rate} error={f.rate} onChange={(e) => { setForm((x) => ({ ...x, rate: e.target.value })) }} />
      </form>
    </Drawer>
  )
}

const SCHEMA = { currency: codecs.id(), page: codecs.positiveInt(1), pageSize: codecs.choiceInt(PAGE_SIZES, 50) }

export function RatesTab() {
  const { t } = useTranslation()
  const { hasPermission } = useSession()
  const [state, setState] = useUrlState(SCHEMA, { pageKey: 'page' })
  const rates = useRates({ currency: state.currency, page: state.page, pageSize: state.pageSize })
  const currencies = useHandbookValues('currency', { activeOnly: true })
  const remove = useDeleteRate()
  const [editor, setEditor] = useState<{ rate: Rate | null; nonce: number } | null>(null)
  const [toDelete, setToDelete] = useState<Rate | null>(null)

  const columns: Column<Rate>[] = [
    { key: 'date', header: t('finance.rates.date'), cell: (r) => <DateTime value={r.date} dateOnly /> },
    { key: 'currency', header: t('finance.rates.currency'), cell: (r) => r.currency.code },
    { key: 'rate', header: t('finance.rates.rate'), align: 'right', cell: (r) => <span className="tabular-nums">{Number(r.rate).toLocaleString('ru-RU', { maximumFractionDigits: 6 })}</span> },
    {
      key: 'actions',
      header: <span className="sr-only">{t('common.actions')}</span>,
      align: 'right',
      cell: (r) => (
        <span className="flex justify-end gap-1">
          <WriteButton variant="ghost" permission="finance.update" aria-label={t('finance.rates.editNamed', { name: `${r.currency.code} ${r.date}` })} onClick={() => { setEditor({ rate: r, nonce: Date.now() }) }}>
            {t('common.edit')}
          </WriteButton>
          {hasPermission('finance.delete') ? (
            <WriteButton variant="ghost" permission="finance.delete" aria-label={t('finance.rates.deleteNamed', { name: `${r.currency.code} ${r.date}` })} onClick={() => { setToDelete(r) }}>
              {t('common.delete')}
            </WriteButton>
          ) : null}
        </span>
      ),
    },
  ]

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <Select
          label={t('finance.rates.currency')}
          hideLabel
          value={state.currency === null ? '' : String(state.currency)}
          placeholder={t('finance.rates.allCurrencies')}
          options={currencies.values.filter((v) => v.code !== BASE_CURRENCY).map((v) => ({ value: String(v.id), label: v.code }))}
          onChange={(value) => { setState({ currency: value ? Number(value) : null }) }}
        />
        <WriteButton variant="primary" permission="finance.create" onClick={() => { setEditor({ rate: null, nonce: Date.now() }) }}>
          {t('finance.rates.add')}
        </WriteButton>
      </div>
      <DataTable
        caption={t('finance.tabs.rates')}
        columns={columns}
        rows={rates.data?.results}
        rowKey={(r) => r.id}
        loading={rates.isPending}
        error={rates.isError ? errorMessage(rates.error, t) : undefined}
        onRetry={() => { void rates.refetch() }}
        empty={<EmptyState title={t('finance.rates.empty')} hint={t('finance.rates.emptyHint')} />}
      />
      <Pagination page={state.page} pageSize={state.pageSize} count={rates.data?.count ?? 0} onPage={(page) => { setState({ page }) }} onPageSize={(pageSize) => { setState({ pageSize }) }} />
      {editor ? <RateDrawer key={editor.nonce} rate={editor.rate} onClose={() => { setEditor(null) }} /> : null}
      <ConfirmDialog
        open={toDelete !== null}
        danger
        title={t('finance.rates.deleteTitle')}
        message={toDelete ? t('finance.rates.deleteMessage', { currency: toDelete.currency.code, date: toDelete.date }) : ''}
        confirmLabel={t('common.delete')}
        busy={remove.isPending}
        error={remove.isError ? errorMessage(remove.error, t) : undefined}
        onCancel={() => { setToDelete(null); remove.reset() }}
        onConfirm={() => { if (toDelete) remove.mutate(toDelete.id, { onSuccess: () => { setToDelete(null) } }) }}
      />
    </div>
  )
}
