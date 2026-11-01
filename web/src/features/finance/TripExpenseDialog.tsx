import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { useFormat } from '../../shared/format/useFormat'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { Spinner } from '../../shared/ui/Spinner'
import { TextField } from '../../shared/ui/TextField'
import { WriteButton } from '../../shared/ui/WriteButton'
import { useCreateTripExpense, useTripExpense } from './hooks'
import { fromCents, toCents } from './invoiceMath'
import type { TripExpenseData } from './types'

function Body({ data, currency, onClose }: { data: TripExpenseData; currency: string; onClose: () => void }) {
  const { t } = useTranslation()
  const { money } = useFormat()
  const [amounts, setAmounts] = useState<Record<number, string>>(() =>
    Object.fromEntries(data.suggestion.map((s) => [s.order_id, s.amount])),
  )
  const [error, setError] = useState<string | undefined>()
  const create = useCreateTripExpense()
  const sum = data.orders.reduce((acc, o) => acc + (toCents(amounts[o.order_id] ?? '') ?? 0n), 0n)
  const price = toCents(data.trip.price) ?? 0n
  const invalid = data.orders.some((o) => toCents(amounts[o.order_id] ?? '') === null)
  const mismatch = invalid || sum !== price

  const submit = () => {
    setError(undefined)
    create.mutate(
      { tripId: data.trip.id, allocations: data.orders.map((o) => ({ order_id: o.order_id, amount: (amounts[o.order_id] ?? '0').trim() })) },
      { onSuccess: onClose, onError: (e) => { setError(errorMessage(e, t)) } },
    )
  }
  return (
    <Dialog
      open
      title={t('finance.tripExpense.title', { number: data.trip.number })}
      onClose={onClose}
      busy={create.isPending}
      footer={
        <>
          <Button onClick={onClose} disabled={create.isPending}>{t('common.cancel')}</Button>
          <WriteButton variant="primary" permission="finance.create" disabled={create.isPending || mismatch} onClick={submit}>
            {t('finance.tripExpense.create')}
          </WriteButton>
        </>
      }
    >
      <div className="space-y-3">
        {error ? <Banner kind="error">{error}</Banner> : null}
        <p className="text-sm">{t('finance.tripExpense.hint', { price: money(data.trip.price, currency) })}</p>
        {data.orders.map((o) => (
          <TextField
            key={o.order_id}
            label={t('finance.tripExpense.amountFor', { number: o.order_number })}
            inputMode="decimal"
            value={amounts[o.order_id] ?? ''}
            onChange={(e) => { setAmounts((x) => ({ ...x, [o.order_id]: e.target.value })) }}
          />
        ))}
        <p className={`text-sm ${mismatch ? 'text-red-600 dark:text-red-400' : ''}`}>
          {t('finance.tripExpense.sum', { sum: money(fromCents(sum), currency) })}
        </p>
      </div>
    </Dialog>
  )
}

export function TripExpenseDialog({ tripId, currency, onClose }: { tripId: number; currency: string; onClose: () => void }) {
  const { t } = useTranslation()
  const query = useTripExpense(tripId)
  if (query.isError) return <Banner kind="error">{errorMessage(query.error, t)}</Banner>
  if (!query.data) return <Spinner />
  return <Body data={query.data} currency={currency} onClose={onClose} />
}
