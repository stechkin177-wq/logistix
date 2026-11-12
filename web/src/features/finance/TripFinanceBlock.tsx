import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { Banner } from '../../shared/ui/Banner'
import { Money } from '../../shared/ui/Money'
import { Spinner } from '../../shared/ui/Spinner'
import { WriteButton } from '../../shared/ui/WriteButton'
import { ExpenseStatusBadge, ReviewBadge } from './LedgerBadges'
import { useCreateCarrierExpense, useTripFinance } from './ledgerHooks'

/** «Финансы рейса» (engine = new): расход перевозчика, расхождение со счётом, кнопка создания расхода. */
export function TripFinanceBlock({ tripId }: { tripId: number }) {
  const { t } = useTranslation()
  const query = useTripFinance(tripId)
  const create = useCreateCarrierExpense()
  const [error, setError] = useState<string | undefined>()
  if (query.isError) return <Banner kind="error">{errorMessage(query.error, t)}</Banner>
  if (!query.data) return <Spinner label={t('table.loading')} />
  const d = query.data
  const cur = d.trip.currency?.code
  const submit = () => {
    if (create.isPending) return // защита от повторной отправки
    setError(undefined)
    create.mutate(tripId, { onError: (e) => { setError(errorMessage(e, t)) } })
  }
  return (
    <section aria-labelledby="trip-finance" className="mt-4 space-y-2">
      <h3 id="trip-finance" className="text-xs font-medium">{t('finance.ledger.tripTitle')}</h3>
      {error ? <Banner kind="error">{error}</Banner> : null}
      <p className="text-sm">{t('finance.ledger.carrierPrice')}: <Money value={d.trip.carrier_price} currency={cur} /></p>
      {d.expense ? (
        <div className="space-y-1 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span>{d.expense.title}</span>
            <ExpenseStatusBadge status={d.expense.status} />
            <ReviewBadge expense={d.expense} />
            <Money value={d.expense.amount} currency={d.expense.currency?.code} />
          </div>
          {d.invoice_variance && Number(d.invoice_variance) !== 0 ? (
            <Banner kind="warning">{t('finance.ledger.variance')}: <Money value={d.invoice_variance} currency={cur} /></Banner>
          ) : null}
        </div>
      ) : (
        <p className="text-sm text-muted">{t('finance.ledger.noCarrierExpense')}</p>
      )}
      {d.can_create_expense ? (
        <WriteButton variant="primary" permission="finance.create" disabled={create.isPending} onClick={submit}>
          {t('finance.ledger.createFromPrice')}
        </WriteButton>
      ) : null}
    </section>
  )
}
