import { useQueries } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { api } from '../../shared/api/client'
import { errorMessage } from '../../shared/api/errors'
import { NO_ERRORS, serverErrors, type FormErrors } from '../../shared/forms/serverErrors'
import { useFocusInvalid } from '../../shared/forms/useFocusInvalid'
import { useFormat } from '../../shared/format/useFormat'
import { useHandbookValues } from '../../shared/handbooks/useHandbook'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { Checkbox } from '../../shared/ui/Checkbox'
import { Combobox, type ComboOption } from '../../shared/ui/Combobox'
import { DateInput } from '../../shared/ui/DateInput'
import { FormBanner } from '../../shared/ui/FormBanner'
import type { Paginated } from '../../shared/ui/Pagination'
import { Select } from '../../shared/ui/Select'
import { Spinner } from '../../shared/ui/Spinner'
import { TextField } from '../../shared/ui/TextField'
import { WriteButton } from '../../shared/ui/WriteButton'
import { listOrderLines } from '../orders/api'
import { useCurrencies, useOrder } from '../orders/hooks'
import type { Order, OrderLine } from '../orders/types'
import { searchActiveCarriers } from '../trips/api'
import { listTrips } from '../trips/api'
import { useTrip } from '../trips/hooks'
import { useInvoice, useSaveInvoice } from './hooks'
import { computeTotals, toCents, vatPercent } from './invoiceMath'
import { TripExpenseDialog } from './TripExpenseDialog'
import type { Invoice, InvoiceDirection, InvoicePayload } from './types'

interface Pick {
  checked: boolean
  title: string
  amount: string
}

const searchOrders = async (q: string, signal: AbortSignal): Promise<ComboOption[]> => {
  const page = await api.get<Paginated<Order>>('/orders/', { q, page_size: 20 }, { signal })
  return page.results.map((o) => ({ id: o.id, label: `${o.number} · ${o.client_name}` }))
}

function initialPicks(invoice: Invoice | null): Record<number, Pick> {
  const picks: Record<number, Pick> = {}
  for (const item of invoice?.items ?? []) {
    if (item.line !== null) picks[item.line] = { checked: true, title: item.title, amount: item.amount_net }
  }
  return picks
}

interface FormProps {
  invoice: Invoice | null
  direction: InvoiceDirection
  orderId: number | null
  tripId: number | null
}

function InvoiceForm({ invoice, direction, orderId: initialOrder, tripId: initialTrip }: FormProps) {
  const { t } = useTranslation()
  const { money } = useFormat()
  const navigate = useNavigate()
  const isOut = direction === 'out'
  const { codeOf } = useCurrencies()
  const vatValues = useHandbookValues('vat_rate', { activeOnly: true })
  const [orderId, setOrderId] = useState<number | null>(initialOrder)
  const [tripId, setTripId] = useState<number | null>(initialTrip)
  const [carrier, setCarrier] = useState<ComboOption | null>(null)
  const orderQuery = useOrder(isOut ? orderId : null)
  const tripQuery = useTrip(isOut ? null : tripId)
  const order = orderQuery.data
  const trip = tripQuery.data

  const [picks, setPicks] = useState<Record<number, Pick>>(() => initialPicks(invoice))
  const [vatId, setVatId] = useState(invoice ? String(invoice.vat_rate.id) : '')
  const [dueDate, setDueDate] = useState(invoice?.due_date ?? '')
  const [external, setExternal] = useState(invoice?.external_number ?? '')
  const [comment, setComment] = useState(invoice?.comment ?? '')
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS)
  const [expenseOpen, setExpenseOpen] = useState(false)
  const save = useSaveInvoice()
  const ref = useRef<HTMLFormElement>(null)
  useFocusInvalid(ref, errors)

  const sourceOrders: { id: number; number: string }[] = isOut ? (order ? [{ id: order.id, number: order.number }] : []) : (trip?.orders ?? [])
  const lineQueries = useQueries({
    queries: sourceOrders.map((o) => ({
      queryKey: ['finance', 'source-lines', o.id],
      queryFn: ({ signal }: { signal: AbortSignal }) => listOrderLines(o.id, signal),
    })),
  })
  const linesLoading = lineQueries.some((q) => q.isPending)
  const rows: { line: OrderLine; orderNumber: string }[] = lineQueries.flatMap((q, i) =>
    (q.data?.results ?? [])
      .filter((l) => Number(isOut ? l.income : l.expense) > 0)
      .map((line) => ({ line, orderNumber: sourceOrders[i]?.number ?? '' })),
  )

  const currencyId = isOut ? order?.currency : trip?.currency
  const currency = codeOf(currencyId)
  const vatValue = vatValues.values.find((v) => String(v.id) === vatId)
  const percent = vatValue ? vatPercent(vatValue.code) : null
  const picked = rows.filter((r) => picks[r.line.id]?.checked)
  const totals = computeTotals(picked.map((r) => picks[r.line.id]?.amount ?? ''), percent ?? 0)

  const toggle = (line: OrderLine, checked: boolean) => {
    setPicks((p) => ({
      ...p,
      [line.id]: { checked, title: p[line.id]?.title ?? line.title, amount: p[line.id]?.amount ?? (isOut ? line.income : line.expense) },
    }))
  }
  const patchPick = (id: number, patch: Partial<Pick>) => { setPicks((p) => ({ ...p, [id]: { ...(p[id] ?? { checked: true, title: '', amount: '' }), ...patch } })) }

  const submit = () => {
    const local: Record<string, string> = {}
    if (isOut ? !order : !trip) local.source = isOut ? t('finance.invoices.pickOrder') : t('finance.invoices.pickTrip')
    if (picked.length === 0) local.items = t('finance.invoices.pickLine')
    if (!vatValue || percent === null) local.vat_rate = t('finance.invoices.pickVat')
    for (const r of picked) {
      const pick = picks[r.line.id]
      if (!pick || toCents(pick.amount) === null) local[`amount.${String(r.line.id)}`] = t('errors.invalidNumber')
      else if (!pick.title.trim()) local[`title.${String(r.line.id)}`] = t('errors.requiredField')
    }
    if (Object.keys(local).length > 0 || !vatValue || currencyId === undefined) {
      setErrors({ fields: local, banner: undefined })
      return
    }
    setErrors(NO_ERRORS)
    const items = picked.map((r) => ({ title: (picks[r.line.id]?.title ?? '').trim(), amount_net: (picks[r.line.id]?.amount ?? '').trim(), line: r.line.id }))
    const body: InvoicePayload = isOut && order
      ? { direction: 'out', party: order.client, order: order.id, currency: currencyId, vat_rate: vatValue.id, items }
      : { direction: 'in', party: trip?.carrier ?? 0, trip: trip?.id, currency: currencyId, vat_rate: vatValue.id, items }
    // при правке черновика пустое значение отправляется явно: иначе очистка поля молча игнорируется
    if (invoice) {
      body.due_date = dueDate || null
      body.comment = comment.trim()
      if (!isOut) body.external_number = external.trim()
    } else {
      if (dueDate) body.due_date = dueDate
      if (comment.trim()) body.comment = comment.trim()
      if (!isOut && external.trim()) body.external_number = external.trim()
    }
    save.mutate(
      { id: invoice?.id ?? null, body },
      {
        onSuccess: (saved) => { void navigate(`/finance/invoices/${String(saved.id)}`) },
        onError: (error) => { setErrors(serverErrors(error, t, (p) => /^(due_date|external_number|comment)$/.test(p))) },
      },
    )
  }
  const f = errors.fields
  const noExpense = !isOut && trip !== undefined && !linesLoading && rows.length === 0

  const orderOption: ComboOption | null = order ? { id: order.id, label: `${order.number} · ${order.client_name}` } : orderId ? { id: orderId, label: `#${String(orderId)}` } : null
  const tripOption: ComboOption | null = trip ? { id: trip.id, label: trip.number } : tripId ? { id: tripId, label: `#${String(tripId)}` } : null
  const carrierOption: ComboOption | null = carrier ?? (trip?.carrier ? { id: trip.carrier, label: trip.carrier_name ?? `#${String(trip.carrier)}` } : null)
  const title = invoice ? t('finance.invoices.editTitle', { id: invoice.id }) : isOut ? t('finance.invoices.createTitle') : t('finance.invoices.createTitleIn')

  return (
    <form ref={ref} noValidate onSubmit={(e) => { e.preventDefault(); submit() }} className="max-w-3xl space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-base font-semibold">{title}</h1>
        <Link className="text-sm text-brand-700 underline dark:text-brand-300" to="/finance?tab=invoices">{t('finance.invoices.backToList')}</Link>
      </div>
      <FormBanner message={errors.banner} />

      {isOut ? (
        <Combobox
          label={t('finance.invoices.selectOrder')}
          required
          queryKey={['finance', 'order-search']}
          fetchOptions={searchOrders}
          value={orderOption}
          error={f.source}
          disabled={invoice !== null}
          onChange={(o) => { setOrderId(o?.id ?? null); setPicks({}) }}
        />
      ) : (
        <div className="grid gap-2 md:grid-cols-2">
          <Combobox
            label={t('finance.invoices.pickCarrier')}
            queryKey={['finance', 'carrier-search']}
            fetchOptions={searchActiveCarriers}
            value={carrierOption}
            disabled={invoice !== null}
            onChange={(o) => { setCarrier(o); setTripId(null); setPicks({}) }}
          />
          <Combobox
            label={t('finance.invoices.selectTrip')}
            required
            queryKey={['finance', 'trip-search', carrierOption?.id ?? 0]}
            fetchOptions={async (q, signal) => {
              const page = await listTrips({ q, order: null, status: null, carrier: carrierOption?.id ?? null, consolidated: false, page: 1, pageSize: 20 }, signal)
              return page.results.map((x) => ({ id: x.id, label: `${x.number}${x.carrier_name ? ` · ${x.carrier_name}` : ''}` }))
            }}
            value={tripOption}
            error={f.source}
            disabled={invoice !== null || carrierOption === null}
            onChange={(o) => { setTripId(o?.id ?? null); setPicks({}) }}
          />
        </div>
      )}

      <fieldset className="space-y-2">
        <legend className="text-sm font-semibold">{t('finance.invoices.lines')}</legend>
        {(isOut ? orderQuery.isError : tripQuery.isError) ? <Banner kind="error">{errorMessage(isOut ? orderQuery.error : tripQuery.error, t)}</Banner> : null}
        {sourceOrders.length === 0 ? <p className="text-sm text-muted">{isOut ? t('finance.invoices.pickOrderFirst') : t('finance.invoices.pickTripFirst')}</p> : null}
        {linesLoading && sourceOrders.length > 0 ? <Spinner /> : null}
        {sourceOrders.length > 0 && !linesLoading && rows.length === 0 && isOut ? <p className="text-sm text-muted">{t('finance.invoices.noLines')}</p> : null}
        {noExpense ? (
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm text-muted">{t('finance.invoices.noTripLines')}</p>
            <WriteButton permission="finance.create" onClick={() => { setExpenseOpen(true) }}>{t('finance.tripExpense.button')}</WriteButton>
          </div>
        ) : null}
        {f.items ? <p role="alert" className="text-xs text-red-600 dark:text-red-400">{f.items}</p> : null}
        {rows.map(({ line, orderNumber }) => {
          const pick = picks[line.id]
          return (
            <div key={line.id} className="grid items-start gap-2 rounded-control border border-line p-2 md:grid-cols-[auto_1fr_10rem]">
              <Checkbox
                label={t('finance.invoices.include', { name: line.title })}
                hideLabel
                checked={pick?.checked ?? false}
                onChange={(e) => { toggle(line, e.target.checked) }}
              />
              <TextField
                label={`${t('finance.invoices.lineTitle')}: ${line.title}`}
                hideLabel
                disabled={!pick?.checked}
                value={pick?.title ?? line.title}
                error={f[`title.${String(line.id)}`]}
                hint={`${orderNumber}${line.category ? ` · ${line.category}` : ''}`}
                onChange={(e) => { patchPick(line.id, { title: e.target.value }) }}
              />
              <TextField
                label={`${t('finance.invoices.amountNet')}: ${line.title}`}
                hideLabel
                inputMode="decimal"
                disabled={!pick?.checked}
                value={pick?.amount ?? (isOut ? line.income : line.expense)}
                error={f[`amount.${String(line.id)}`]}
                onChange={(e) => { patchPick(line.id, { amount: e.target.value }) }}
              />
            </div>
          )
        })}
      </fieldset>

      <div className="grid gap-2 md:grid-cols-3">
        <Select
          label={t('finance.invoices.vatRate')}
          required
          value={vatId}
          placeholder="—"
          options={vatValues.values.map((v) => ({ value: String(v.id), label: v.name }))}
          error={f.vat_rate}
          onChange={setVatId}
        />
        <DateInput label={t('finance.invoices.dueDate')} value={dueDate} error={f.due_date} onChange={setDueDate} />
        {!isOut ? <TextField label={t('finance.invoices.externalNumber')} value={external} error={f.external_number} onChange={(e) => { setExternal(e.target.value) }} /> : null}
      </div>
      <TextField label={t('finance.invoices.comment')} value={comment} error={f.comment} onChange={(e) => { setComment(e.target.value) }} />

      <div role="group" aria-label={t('finance.invoices.totals')} className="ml-auto grid max-w-xs grid-cols-2 gap-x-3 gap-y-1 text-sm">
        <span>{t('finance.invoices.net')}</span><span className="text-right tabular-nums">{money(totals.net, currency)}</span>
        <span>{t('finance.invoices.vat')}</span><span className="text-right tabular-nums">{money(totals.vat, currency)}</span>
        <span className="font-semibold">{t('finance.invoices.gross')}</span><span className="text-right font-semibold tabular-nums">{money(totals.gross, currency)}</span>
      </div>

      <div className="flex justify-end gap-2">
        <Button onClick={() => { void navigate('/finance?tab=invoices') }} disabled={save.isPending}>{t('common.cancel')}</Button>
        <WriteButton type="submit" variant="primary" permission={invoice ? 'finance.update' : 'finance.create'} disabled={save.isPending}>
          {save.isPending ? t('common.saving') : t('finance.invoices.saveDraft')}
        </WriteButton>
      </div>
      {expenseOpen && trip ? <TripExpenseDialog tripId={trip.id} currency={currency} onClose={() => { setExpenseOpen(false) }} /> : null}
    </form>
  )
}

/** Новый счёт (?direction=in|out, ?order=, ?trip=) или правка черновика (/finance/invoices/:id/edit). */
export function InvoiceFormPage() {
  const { t } = useTranslation()
  const params = useParams()
  const [search] = useSearchParams()
  const editId = params.id !== undefined && /^\d{1,12}$/.test(params.id) ? Number(params.id) : null
  const loaded = useInvoice(editId)
  const num = (key: string) => (/^\d{1,12}$/.test(search.get(key) ?? '') ? Number(search.get(key)) : null)

  if (params.id !== undefined) {
    if (editId === null || loaded.isError) return <Banner kind="error">{loaded.isError ? errorMessage(loaded.error, t) : t('errors.notFound')}</Banner>
    if (!loaded.data) return <Spinner />
    if (loaded.data.status !== 'draft') return <Banner kind="info">{t('finance.invoices.onlyDraftEditable')}</Banner>
    const inv = loaded.data
    return <InvoiceForm key={inv.id} invoice={inv} direction={inv.direction} orderId={inv.order?.id ?? null} tripId={inv.trip?.id ?? null} />
  }
  const direction: InvoiceDirection = search.get('direction') === 'in' ? 'in' : 'out'
  return <InvoiceForm key={`${direction}-${String(num('order'))}-${String(num('trip'))}`} invoice={null} direction={direction} orderId={num('order')} tripId={num('trip')} />
}
