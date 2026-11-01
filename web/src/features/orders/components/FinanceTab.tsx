import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../../shared/api/errors'
import { useSession } from '../../../shared/auth/useSession'
import { serverErrors, NO_ERRORS, type FormErrors } from '../../../shared/forms/serverErrors'
import { useFocusInvalid } from '../../../shared/forms/useFocusInvalid'
import { useFormat } from '../../../shared/format/useFormat'
import { toInputDateTime } from '../../../shared/format/datetime'
import { Badge } from '../../../shared/ui/Badge'
import { Banner } from '../../../shared/ui/Banner'
import { Button } from '../../../shared/ui/Button'
import { ConfirmDialog } from '../../../shared/ui/ConfirmDialog'
import { DataTable, type Column } from '../../../shared/ui/DataTable'
import { DateInput } from '../../../shared/ui/DateInput'
import { DateTime } from '../../../shared/ui/DateTime'
import { Drawer } from '../../../shared/ui/Drawer'
import { EmptyState } from '../../../shared/ui/EmptyState'
import { FormBanner } from '../../../shared/ui/FormBanner'
import { Money } from '../../../shared/ui/Money'
import { TextField } from '../../../shared/ui/TextField'
import { WriteButton } from '../../../shared/ui/WriteButton'
import { useCurrencies, useDeleteOrderLine, useOrderLines, useSaveOrderLine } from '../hooks'
import { OrderInvoicesBlock } from './OrderInvoicesBlock'
import type { Order, OrderLine } from '../types'

const MONEY_RE = /^\d{1,12}(\.\d{1,2})?$/
const KNOWN = /^(title|category|income|expense|date)$/

function LineDrawer({ order, line, onClose }: { order: Order; line: OrderLine | null; onClose: () => void }) {
  const { t } = useTranslation()
  const { session } = useSession()
  const today = toInputDateTime(new Date().toISOString(), session?.company.timezone).slice(0, 10)
  const [form, setForm] = useState({
    title: line?.title ?? '', category: line?.category ?? '', income: line?.income ?? '0', expense: line?.expense ?? '0', date: line?.date ?? today,
  })
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS)
  const save = useSaveOrderLine()
  const ref = useRef<HTMLFormElement>(null)
  useFocusInvalid(ref, errors)
  const permission = line ? 'finance.update' : 'finance.create'

  const submit = () => {
    const local: Record<string, string> = {}
    if (!form.title.trim()) local.title = t('errors.requiredField')
    if (!MONEY_RE.test(form.income.trim())) local.income = t('errors.invalidNumber')
    if (!MONEY_RE.test(form.expense.trim())) local.expense = t('errors.invalidNumber')
    if (!form.date) local.date = t('errors.invalidDate')
    if (Object.keys(local).length > 0) {
      setErrors({ fields: local, banner: undefined })
      return
    }
    setErrors(NO_ERRORS)
    save.mutate(
      { id: line?.id ?? null, body: { order: order.id, title: form.title.trim(), category: form.category.trim(), income: form.income.trim(), expense: form.expense.trim(), date: form.date } },
      { onSuccess: onClose, onError: (error) => { setErrors(serverErrors(error, t, (p) => KNOWN.test(p))) } },
    )
  }
  const f = errors.fields
  const set = (key: keyof typeof form, value: string) => { setForm((x) => ({ ...x, [key]: value })) }
  return (
    <Drawer
      open
      title={line ? t('orders.editLine') : t('orders.addLine')}
      onClose={onClose}
      busy={save.isPending}
      footer={
        <>
          <Button onClick={onClose} disabled={save.isPending}>{t('common.cancel')}</Button>
          <WriteButton variant="primary" permission={permission} disabled={save.isPending} onClick={submit}>
            {save.isPending ? t('common.saving') : t('common.save')}
          </WriteButton>
        </>
      }
    >
      <form ref={ref} noValidate onSubmit={(e) => { e.preventDefault(); submit() }} className="space-y-3">
        <FormBanner message={errors.banner} />
        <TextField label={t('orders.lineTitle')} required value={form.title} error={f.title} onChange={(e) => { set('title', e.target.value) }} />
        <TextField label={t('orders.lineCategory')} value={form.category} error={f.category} onChange={(e) => { set('category', e.target.value) }} />
        <div className="grid grid-cols-2 gap-2">
          <TextField label={t('orders.income')} inputMode="decimal" value={form.income} error={f.income} onChange={(e) => { set('income', e.target.value) }} />
          <TextField label={t('orders.expense')} inputMode="decimal" value={form.expense} error={f.expense} onChange={(e) => { set('expense', e.target.value) }} />
        </div>
        <DateInput label={t('orders.lineDate')} value={form.date} error={f.date} onChange={(v) => { set('date', v) }} />
      </form>
    </Drawer>
  )
}

export function FinanceTab({ order }: { order: Order }) {
  const { t } = useTranslation()
  const { hasPermission } = useSession()
  const lines = useOrderLines(order.id, true)
  const { codeOf } = useCurrencies()
  const remove = useDeleteOrderLine()
  const [editor, setEditor] = useState<{ line: OrderLine | null; nonce: number } | null>(null)
  const [toDelete, setToDelete] = useState<OrderLine | null>(null)
  const code = codeOf(order.currency)
  const { money } = useFormat()

  const columns: Column<OrderLine>[] = [
    { key: 'date', header: t('orders.lineDate'), cell: (l) => <DateTime value={l.date} dateOnly /> },
    {
      key: 'title',
      header: t('orders.lineTitle'),
      cell: (l) => (
        <span className="flex items-center gap-1">
          {l.title}
          {l.is_base ? <Badge tone="info" title={t('orders.baseLineHint')}>{t('orders.baseLineLocked')}</Badge> : null}
        </span>
      ),
    },
    { key: 'category', header: t('orders.lineCategory'), cell: (l) => l.category || '—' },
    { key: 'income', header: t('orders.income'), align: 'right', cell: (l) => <Money value={l.income} currency={code} /> },
    { key: 'expense', header: t('orders.expense'), align: 'right', cell: (l) => <Money value={l.expense} currency={code} /> },
    {
      key: 'actions',
      header: <span className="sr-only">{t('common.actions')}</span>,
      align: 'right',
      cell: (l) =>
        l.is_base ? null : (
          <span className="flex justify-end gap-1">
            <WriteButton variant="ghost" permission="finance.update" aria-label={t('orders.editLineNamed', { name: l.title })} onClick={() => { setEditor({ line: l, nonce: Date.now() }) }}>
              {t('common.edit')}
            </WriteButton>
            {hasPermission('finance.delete') ? (
              <WriteButton variant="ghost" permission="finance.delete" aria-label={t('orders.deleteLineNamed', { name: l.title })} onClick={() => { setToDelete(l) }}>
                {t('common.delete')}
              </WriteButton>
            ) : null}
          </span>
        ),
    },
  ]

  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-2 gap-2 md:grid-cols-4">
        {([
          ['orders.revenue', <Money key="r" value={order.revenue} currency={code} />],
          ['orders.cost', <Money key="c" value={order.cost} currency={code} />],
          ['orders.profit', <Money key="p" value={order.profit} currency={code} />],
          ['orders.margin', order.margin_pct === null ? '—' : <span key="m" className="tabular-nums">{money(order.margin_pct)} %</span>],
        ] as const).map(([label, value]) => (
          <div key={label} className="rounded border border-slate-200 bg-white p-2 dark:border-slate-800 dark:bg-slate-900">
            <dt className="text-xs text-slate-500">{t(label)}</dt>
            <dd className="text-base font-semibold">{value}</dd>
          </div>
        ))}
      </dl>
      <Banner kind="info">{t('orders.baseLineHint')}</Banner>
      {hasPermission('finance.create') ? (
        <WriteButton permission="finance.create" onClick={() => { setEditor({ line: null, nonce: Date.now() }) }}>
          {t('orders.addLine')}
        </WriteButton>
      ) : null}
      <DataTable
        caption={t('orders.tabFinance')}
        columns={columns}
        rows={lines.data?.results}
        rowKey={(l) => l.id}
        loading={lines.isFetching}
        error={lines.isError ? errorMessage(lines.error, t) : undefined}
        onRetry={() => void lines.refetch()}
        empty={<EmptyState title={t('orders.noLines')} />}
      />
      <OrderInvoicesBlock order={order} currency={code} />
      {editor ? <LineDrawer key={editor.nonce} order={order} line={editor.line} onClose={() => { setEditor(null) }} /> : null}
      <ConfirmDialog
        open={toDelete !== null}
        danger
        title={t('orders.deleteLineTitle')}
        message={t('orders.deleteLineMessage', { name: toDelete?.title ?? '' })}
        confirmLabel={t('common.delete')}
        busy={remove.isPending}
        error={remove.isError ? errorMessage(remove.error, t) : undefined}
        onCancel={() => { setToDelete(null); remove.reset() }}
        onConfirm={() => {
          if (toDelete) remove.mutate(toDelete.id, { onSuccess: () => { setToDelete(null) } })
        }}
      />
    </div>
  )
}
