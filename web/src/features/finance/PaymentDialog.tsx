import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { useSession } from '../../shared/auth/useSession'
import { toInputDateTime } from '../../shared/format/datetime'
import { useFormat } from '../../shared/format/useFormat'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { DateInput } from '../../shared/ui/DateInput'
import { Dialog } from '../../shared/ui/Dialog'
import { Select } from '../../shared/ui/Select'
import { TextField } from '../../shared/ui/TextField'
import { WriteButton } from '../../shared/ui/WriteButton'
import { useAddPayment } from './hooks'
import { invoiceLabel } from './StatusBadge'
import { toCents } from './invoiceMath'
import type { Invoice, PaymentMethod } from './types'

const METHODS: PaymentMethod[] = ['bank', 'cash', 'other']

export function PaymentDialog({ invoice, onClose }: { invoice: Invoice; onClose: () => void }) {
  const { t } = useTranslation()
  const { money } = useFormat()
  const { session } = useSession()
  const today = toInputDateTime(new Date().toISOString(), session?.company.timezone).slice(0, 10)
  const [form, setForm] = useState({ date: today, amount: invoice.balance, method: 'bank' as PaymentMethod, payment_ref: '', comment: '' })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [banner, setBanner] = useState<string | undefined>()
  const add = useAddPayment()
  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) => { setForm((x) => ({ ...x, [key]: value })) }

  const submit = () => {
    const local: Record<string, string> = {}
    const cents = toCents(form.amount)
    const balance = toCents(invoice.balance) ?? 0n
    if (cents === null || cents <= 0n) local.amount = t('errors.invalidNumber')
    else if (cents > balance) local.amount = t('finance.payments.exceeds', { balance: money(invoice.balance, invoice.currency.code) })
    if (!form.date) local.date = t('errors.invalidDate')
    setErrors(local)
    if (Object.keys(local).length > 0) return
    setBanner(undefined)
    add.mutate(
      {
        invoiceId: invoice.id,
        body: {
          date: form.date, amount: form.amount.trim(), method: form.method,
          ...(form.payment_ref.trim() ? { payment_ref: form.payment_ref.trim() } : {}),
          ...(form.comment.trim() ? { comment: form.comment.trim() } : {}),
        },
      },
      { onSuccess: onClose, onError: (error) => { setBanner(errorMessage(error, t)) } },
    )
  }

  return (
    <Dialog
      open
      title={t('finance.payments.addTitle', { number: invoiceLabel(invoice, t) })}
      onClose={onClose}
      busy={add.isPending}
      footer={
        <>
          <Button onClick={onClose} disabled={add.isPending}>{t('common.cancel')}</Button>
          <WriteButton variant="primary" permission="finance.create" disabled={add.isPending} onClick={submit}>
            {add.isPending ? t('common.saving') : t('common.save')}
          </WriteButton>
        </>
      }
    >
      <form noValidate onSubmit={(e) => { e.preventDefault(); submit() }} className="space-y-3">
        {banner ? <Banner kind="error">{banner}</Banner> : null}
        <div className="grid grid-cols-2 gap-2">
          <DateInput label={t('finance.payments.date')} required value={form.date} error={errors.date} onChange={(v) => { set('date', v) }} />
          <TextField label={t('finance.payments.amount')} required inputMode="decimal" value={form.amount} error={errors.amount} onChange={(e) => { set('amount', e.target.value) }} />
        </div>
        <Select label={t('finance.payments.method')} value={form.method} options={METHODS.map((m) => ({ value: m, label: t(`finance.payments.methods.${m}`) }))} onChange={(v) => { set('method', v as PaymentMethod) }} />
        <TextField label={t('finance.payments.ref')} value={form.payment_ref} onChange={(e) => { set('payment_ref', e.target.value) }} />
        <TextField label={t('finance.payments.comment')} value={form.comment} onChange={(e) => { set('comment', e.target.value) }} />
      </form>
    </Dialog>
  )
}
