import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router'
import { ApiError, errorMessage } from '../../shared/api/errors'
import { useSession } from '../../shared/auth/useSession'
import { NO_ERRORS, serverErrors, type FormErrors } from '../../shared/forms/serverErrors'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { ConfirmDialog } from '../../shared/ui/ConfirmDialog'
import { DataTable, type Column } from '../../shared/ui/DataTable'
import { DateInput } from '../../shared/ui/DateInput'
import { DateTime } from '../../shared/ui/DateTime'
import { Drawer } from '../../shared/ui/Drawer'
import { EmptyState } from '../../shared/ui/EmptyState'
import { FormBanner } from '../../shared/ui/FormBanner'
import { Money } from '../../shared/ui/Money'
import { Spinner } from '../../shared/ui/Spinner'
import { TextField } from '../../shared/ui/TextField'
import { IssueDocumentButton } from '../documents/IssueDocumentButton'
import { WriteButton } from '../../shared/ui/WriteButton'
import {
  useCancelInvoice, useDeleteInvoice, useDeletePayment, useInvoice, useInvoicePayments, useIssueInvoice, useSaveInvoice,
} from './hooks'
import { OverrideDialog } from './OverrideDialog'
import { PaymentDialog } from './PaymentDialog'
import { StatusBadge, invoiceLabel } from './StatusBadge'
import type { Invoice, InvoiceItem, Payment } from './types'

function LightEditDrawer({ invoice, onClose }: { invoice: Invoice; onClose: () => void }) {
  const { t } = useTranslation()
  const [form, setForm] = useState({ due_date: invoice.due_date ?? '', external_number: invoice.external_number, comment: invoice.comment })
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS)
  const save = useSaveInvoice()
  const submit = () => {
    save.mutate(
      { id: invoice.id, body: { due_date: form.due_date || null, external_number: form.external_number.trim(), comment: form.comment.trim() } },
      { onSuccess: onClose, onError: (error) => { setErrors(serverErrors(error, t, (p) => /^(due_date|external_number|comment)$/.test(p))) } },
    )
  }
  return (
    <Drawer
      open
      title={t('finance.invoices.dueEdit')}
      onClose={onClose}
      busy={save.isPending}
      footer={
        <>
          <Button onClick={onClose} disabled={save.isPending}>{t('common.cancel')}</Button>
          <WriteButton variant="primary" permission="finance.update" disabled={save.isPending} onClick={submit}>
            {save.isPending ? t('common.saving') : t('common.save')}
          </WriteButton>
        </>
      }
    >
      <form noValidate onSubmit={(e) => { e.preventDefault(); submit() }} className="space-y-3">
        <FormBanner message={errors.banner} />
        <DateInput label={t('finance.invoices.dueDate')} value={form.due_date} error={errors.fields.due_date} onChange={(v) => { setForm((x) => ({ ...x, due_date: v })) }} />
        {invoice.direction === 'in' ? (
          <TextField label={t('finance.invoices.externalNumber')} value={form.external_number} error={errors.fields.external_number} onChange={(e) => { setForm((x) => ({ ...x, external_number: e.target.value })) }} />
        ) : null}
        <TextField label={t('finance.invoices.comment')} value={form.comment} error={errors.fields.comment} onChange={(e) => { setForm((x) => ({ ...x, comment: e.target.value })) }} />
      </form>
    </Drawer>
  )
}

function PaymentsBlock({ invoice }: { invoice: Invoice }) {
  const { t } = useTranslation()
  const { hasPermission } = useSession()
  const payments = useInvoicePayments(invoice.id)
  const remove = useDeletePayment()
  const [toDelete, setToDelete] = useState<Payment | null>(null)
  const code = invoice.currency.code
  const columns: Column<Payment>[] = [
    { key: 'date', header: t('finance.payments.date'), cell: (p) => <DateTime value={p.date} dateOnly /> },
    { key: 'amount', header: t('finance.payments.amount'), align: 'right', cell: (p) => <Money value={p.amount} currency={code} /> },
    { key: 'method', header: t('finance.payments.method'), cell: (p) => t(`finance.payments.methods.${p.method}`) },
    { key: 'ref', header: t('finance.payments.ref'), cell: (p) => p.payment_ref || '—' },
    { key: 'fx', header: t('finance.payments.fx'), align: 'right', cell: (p) => <Money value={p.fx_difference_kzt} /> },
    {
      key: 'actions',
      header: <span className="sr-only">{t('common.actions')}</span>,
      align: 'right',
      cell: (p) =>
        hasPermission('finance.delete') ? (
          <WriteButton variant="ghost" permission="finance.delete" aria-label={t('finance.payments.deleteNamed', { date: p.date })} onClick={() => { setToDelete(p) }}>
            {t('common.delete')}
          </WriteButton>
        ) : null,
    },
  ]
  return (
    <section className="space-y-2">
      <h2 className="text-sm font-semibold">{t('finance.invoices.payments')}</h2>
      <DataTable
        caption={t('finance.invoices.payments')}
        columns={columns}
        rows={payments.data?.results}
        rowKey={(p) => p.id}
        loading={payments.isPending}
        error={payments.isError ? errorMessage(payments.error, t) : undefined}
        onRetry={() => { void payments.refetch() }}
        empty={<EmptyState title={t('finance.invoices.noPayments')} />}
      />
      <ConfirmDialog
        open={toDelete !== null}
        danger
        title={t('finance.payments.deleteTitle')}
        message={toDelete ? t('finance.payments.deleteMessage', { amount: toDelete.amount, date: toDelete.date }) : ''}
        confirmLabel={t('common.delete')}
        busy={remove.isPending}
        error={remove.isError ? errorMessage(remove.error, t) : undefined}
        onCancel={() => { setToDelete(null); remove.reset() }}
        onConfirm={() => { if (toDelete) remove.mutate(toDelete.id, { onSuccess: () => { setToDelete(null) } }) }}
      />
    </section>
  )
}

export function InvoiceDetailPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { hasPermission } = useSession()
  const params = useParams()
  const id = /^\d{1,12}$/.test(params.id ?? '') ? Number(params.id) : null
  const query = useInvoice(id)
  const issue = useIssueInvoice()
  const cancel = useCancelInvoice()
  const remove = useDeleteInvoice()
  const [dialog, setDialog] = useState<'payment' | 'cancel' | 'delete' | 'edit' | 'override' | null>(null)
  const [error, setError] = useState<string | undefined>()
  const [overrideError, setOverrideError] = useState<string | undefined>()

  if (id === null || query.isError) {
    return <Banner kind="error">{query.isError ? errorMessage(query.error, t) : t('errors.notFound')}</Banner>
  }
  const invoice = query.data
  if (!invoice) return <Spinner />
  const code = invoice.currency.code
  const isDraft = invoice.status === 'draft'
  const isIssued = invoice.status === 'issued'

  const runIssue = (reason?: string) => {
    setError(undefined)
    setOverrideError(undefined)
    issue.mutate(
      { id: invoice.id, overrideReason: reason },
      {
        onSuccess: () => { setDialog(null) },
        onError: (e) => {
          if (e instanceof ApiError && e.code === 'credit_limit_exceeded' && !reason) setDialog('override')
          else if (reason) setOverrideError(errorMessage(e, t))
          else setError(errorMessage(e, t))
        },
      },
    )
  }

  const itemColumns: Column<InvoiceItem>[] = [
    { key: 'title', header: t('finance.invoices.lineTitle'), cell: (i) => i.title },
    { key: 'amount', header: t('finance.invoices.amountNet'), align: 'right', cell: (i) => <Money value={i.amount_net} currency={code} /> },
  ]

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-base font-semibold">{invoiceLabel(invoice, t)}</h1>
          <StatusBadge status={invoice.display_status} />
          <span className="text-xs text-muted">{t(`finance.direction.${invoice.direction}`)}</span>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link className="text-sm text-brand-700 underline dark:text-brand-300" to="/finance?tab=invoices">{t('finance.invoices.backToList')}</Link>
          {isDraft ? (
            <>
              <WriteButton permission="finance.update" onClick={() => { void navigate(`/finance/invoices/${String(invoice.id)}/edit`) }}>{t('finance.invoices.edit')}</WriteButton>
              <WriteButton variant="primary" permission="finance.update" disabled={issue.isPending} onClick={() => { runIssue() }}>{t('finance.invoices.issue')}</WriteButton>
              <WriteButton permission="finance.delete" onClick={() => { setDialog('delete') }}>{t('finance.invoices.deleteDraft')}</WriteButton>
            </>
          ) : null}
          {isIssued ? (
            <>
              {invoice.direction === 'out' ? (
                <>
                  <IssueDocumentButton kind="invoice_print" source={{ invoice: invoice.id }} label={t('documents.kind.invoice_print')} />
                  <IssueDocumentButton kind="act" source={{ invoice: invoice.id }} label={t('documents.kind.act')} />
                </>
              ) : null}
              <WriteButton permission="finance.update" onClick={() => { setDialog('edit') }}>{t('finance.invoices.dueEdit')}</WriteButton>
              {Number(invoice.balance) > 0 && hasPermission('finance.create') ? (
                <WriteButton variant="primary" permission="finance.create" onClick={() => { setDialog('payment') }}>{t('finance.invoices.addPayment')}</WriteButton>
              ) : null}
              {hasPermission('finance.cancel_invoice') ? (
                <WriteButton permission="finance.cancel_invoice" onClick={() => { setDialog('cancel') }}>{t('finance.invoices.cancelInvoice')}</WriteButton>
              ) : null}
            </>
          ) : null}
        </div>
      </div>
      {error ? <Banner kind="error">{error}</Banner> : null}

      <dl className="grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
        <div><dt className="text-xs text-muted">{invoice.client ? t('finance.invoices.client') : t('finance.invoices.carrier')}</dt><dd>{invoice.client?.name ?? invoice.carrier?.name}</dd></div>
        <div><dt className="text-xs text-muted">{t('finance.invoices.order')}</dt><dd>{invoice.order ? <Link className="text-brand-700 underline dark:text-brand-300" to={`/orders/${String(invoice.order.id)}`}>{invoice.order.number}</Link> : '—'}</dd></div>
        <div><dt className="text-xs text-muted">{t('finance.invoices.trip')}</dt><dd>{invoice.trip?.number ?? '—'}</dd></div>
        <div><dt className="text-xs text-muted">{t('finance.invoices.externalNumber')}</dt><dd>{invoice.external_number || '—'}</dd></div>
        <div><dt className="text-xs text-muted">{t('finance.invoices.issueDate')}</dt><dd>{invoice.issue_date ? <DateTime value={invoice.issue_date} dateOnly /> : '—'}</dd></div>
        <div><dt className="text-xs text-muted">{t('finance.invoices.dueDate')}</dt><dd>{invoice.due_date ? <DateTime value={invoice.due_date} dateOnly /> : '—'}</dd></div>
        <div><dt className="text-xs text-muted">{t('finance.invoices.vatRate')}</dt><dd>{invoice.vat_rate.name}</dd></div>
        <div><dt className="text-xs text-muted">{t('finance.invoices.rateToKzt')}</dt><dd>{invoice.rate_to_kzt ? Number(invoice.rate_to_kzt).toLocaleString('ru-RU', { maximumFractionDigits: 6 }) : '—'}</dd></div>
      </dl>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold">{t('finance.invoices.items')}</h2>
        <DataTable caption={t('finance.invoices.items')} columns={itemColumns} rows={invoice.items} rowKey={(i) => i.id} />
        <dl className="ml-auto grid max-w-xs grid-cols-2 gap-x-3 gap-y-1 text-sm">
          <dt>{t('finance.invoices.net')}</dt><dd className="text-right"><Money value={invoice.totals.net} currency={code} /></dd>
          <dt>{t('finance.invoices.vat')}</dt><dd className="text-right"><Money value={invoice.totals.vat} currency={code} /></dd>
          <dt className="font-semibold">{t('finance.invoices.gross')}</dt><dd className="text-right font-semibold"><Money value={invoice.totals.gross} currency={code} /></dd>
          <dt>{t('finance.invoices.paid')}</dt><dd className="text-right"><Money value={invoice.paid} currency={code} /></dd>
          <dt>{t('finance.invoices.balance')}</dt><dd className="text-right"><Money value={invoice.balance} currency={code} /></dd>
        </dl>
        {invoice.comment ? <p className="text-sm text-muted">{invoice.comment}</p> : null}
      </section>

      {invoice.status !== 'draft' ? <PaymentsBlock invoice={invoice} /> : null}

      {dialog === 'payment' ? <PaymentDialog invoice={invoice} onClose={() => { setDialog(null) }} /> : null}
      {dialog === 'edit' ? <LightEditDrawer invoice={invoice} onClose={() => { setDialog(null) }} /> : null}
      {dialog === 'override' ? (
        <OverrideDialog
          canOverride={hasPermission('finance.override_limit')}
          busy={issue.isPending}
          error={overrideError}
          onConfirm={(reason) => { runIssue(reason) }}
          onCancel={() => { setDialog(null); setOverrideError(undefined) }}
        />
      ) : null}
      <ConfirmDialog
        open={dialog === 'cancel'}
        danger
        title={t('finance.invoices.cancelTitle')}
        message={t('finance.invoices.cancelMessage', { number: invoice.number })}
        confirmLabel={t('finance.invoices.cancelInvoice')}
        busy={cancel.isPending}
        error={cancel.isError ? errorMessage(cancel.error, t) : undefined}
        onCancel={() => { setDialog(null); cancel.reset() }}
        onConfirm={() => { cancel.mutate(invoice.id, { onSuccess: () => { setDialog(null) } }) }}
      />
      <ConfirmDialog
        open={dialog === 'delete'}
        danger
        title={t('finance.invoices.deleteTitle')}
        message={t('finance.invoices.deleteMessage')}
        confirmLabel={t('common.delete')}
        busy={remove.isPending}
        error={remove.isError ? errorMessage(remove.error, t) : undefined}
        onCancel={() => { setDialog(null); remove.reset() }}
        onConfirm={() => { remove.mutate(invoice.id, { onSuccess: () => { void navigate('/finance?tab=invoices') } }) }}
      />
    </div>
  )
}
