import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSession } from '../../../shared/auth/useSession'
import { serverErrors, type FormErrors } from '../../../shared/forms/serverErrors'
import { useFocusInvalid } from '../../../shared/forms/useFocusInvalid'
import { selectableValues, useHandbookValues } from '../../../shared/handbooks/useHandbook'
import { useUsers, userLabel } from '../../../shared/users/useUsers'
import { Button } from '../../../shared/ui/Button'
import { Combobox } from '../../../shared/ui/Combobox'
import { FormBanner } from '../../../shared/ui/FormBanner'
import { Select } from '../../../shared/ui/Select'
import { TextArea, TextField } from '../../../shared/ui/TextField'
import { WriteButton } from '../../../shared/ui/WriteButton'
import { getParty } from '../../parties/api'
import { searchClients } from '../../clients/api'
import { useQuery } from '@tanstack/react-query'
import {
  ORDER_KNOWN_PATH, emptyConsignment, initialOrderState, type ConsignmentForm, orderPayload, validateOrder, type OrderFormState,
} from '../orderForm'
import type { Order } from '../types'
import { CargoFields, RouteFields } from './ConsignmentFields'

interface Props {
  mode: 'create' | 'edit'
  order: Order | null
  submitting: boolean
  /** Ошибка мутации (ApiError) - раскладывается по полям формы. */
  error: unknown
  onSubmit: (body: Record<string, unknown>) => void
  onCancel: () => void
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section aria-label={title} className="space-y-2 rounded-card border border-line bg-surface p-4 shadow-card">
      <h2 className="text-sm font-semibold">{title}</h2>
      {children}
    </section>
  )
}

/** Форма заказа из четырёх блоков (создание) либо из двух (правка: грузы меняются на вкладке «Грузы»). */
export function OrderForm({ mode, order, submitting, error, onSubmit, onCancel }: Props) {
  const { t } = useTranslation()
  const { session } = useSession()
  const tz = session?.company.timezone
  const users = useUsers()
  const currency = useHandbookValues('currency')
  const transport = useHandbookValues('transport_condition')
  const delay = useHandbookValues('payment_delay_condition')
  const defaultCurrency = currency.values.find((v) => v.code === 'KZT')?.id
  const [form, setForm] = useState<OrderFormState>(() =>
    initialOrderState(order, { manager: session?.user.id, currency: undefined }),
  )
  const [local, setLocal] = useState<Record<string, string>>({})
  const [extraOpen, setExtraOpen] = useState(false)
  const formRef = useRef<HTMLFormElement>(null)
  const server: FormErrors = serverErrors(error, t, (path) => ORDER_KNOWN_PATH.test(path))
  const errors = { ...server.fields, ...local }
  useFocusInvalid(formRef, local)
  useFocusInvalid(formRef, error)

  const EXTRA_KEYS = ['contract_number', 'client_ref', 'contact', 'forwarder', 'extra_managers', 'transport_condition', 'delivery_days', 'payment_delay_days', 'payment_delay_condition'] as const
  // дополнительные поля открыты сами, если в них уже есть значения (правка заказа) или ошибки проверки
  const showExtra =
    extraOpen ||
    EXTRA_KEYS.some((k) => (k === 'extra_managers' ? form.extra_managers.length > 0 : Boolean(form[k]))) ||
    EXTRA_KEYS.some((k) => errors[k])
  const clientId = form.client?.id ?? null
  const clientDetail = useQuery({
    queryKey: ['clients', 'detail', clientId],
    queryFn: ({ signal }) => getParty('clients', clientId ?? 0, signal),
    enabled: clientId !== null,
    staleTime: 60_000,
  })
  const contacts = clientDetail.data?.contacts ?? []

  const set = <K extends keyof OrderFormState>(key: K, value: OrderFormState[K]) => {
    setForm((f) => ({ ...f, [key]: value }))
    setLocal((e) => Object.fromEntries(Object.entries(e).filter(([k]) => k !== key)))
  }

  const setCargo = (index: number, next: ConsignmentForm) => {
    setForm((f) => ({ ...f, consignments: f.consignments.map((x, i) => (i === index ? next : x)) }))
  }

  const activeUsers = users.users.filter((u) => u.is_active || String(u.user_id) === form.manager)
  const userOptions = activeUsers.map((u) => ({ value: String(u.user_id), label: userLabel(u) }))
  const currencyValue = form.currency || (defaultCurrency !== undefined ? String(defaultCurrency) : '')

  const submit = () => {
    const problems = validateOrder(form, mode, t)
    setLocal(problems)
    if (Object.keys(problems).length > 0) return
    onSubmit(orderPayload({ ...form, currency: currencyValue }, mode, tz, { sendManagers: users.allowed }))
  }

  return (
    <form
      ref={formRef}
      noValidate
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
      className="space-y-3"
    >
      <FormBanner message={server.banner} />

      <Block title={t('orders.blockContacts')}>
        <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
          <Combobox
            label={t('orders.client')}
            required
            value={form.client}
            queryKey={['clients', 'search']}
            fetchOptions={searchClients}
            error={errors.client}
            onChange={(client) => {
              setForm((f) => ({ ...f, client, contact: '' }))
              setLocal((e) => Object.fromEntries(Object.entries(e).filter(([k]) => k !== 'client')))
            }}
          />
          {users.allowed ? (
            <>
              <Select label={t('orders.manager')} value={form.manager} options={userOptions} error={errors.manager} onChange={(v) => { set('manager', v) }} />
            </>
          ) : (
            <p className="text-xs text-muted md:col-span-3">{t('orders.managerSelf')}</p>
          )}
        </div>
      </Block>

      <Block title={t('orders.blockPrice')}>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          <TextField label={t('orders.clientRate')} inputMode="decimal" required value={form.client_rate} error={errors.client_rate} onChange={(e) => { set('client_rate', e.target.value) }} />
          {currency.allowed ? (
            <Select label={t('orders.currency')} value={currencyValue} options={selectableValues(currency.all, order?.currency).map((v) => ({ value: String(v.id), label: v.code || v.name }))} error={errors.currency} onChange={(v) => { set('currency', v) }} />
          ) : null}
          <TextArea fieldClassName="col-span-2 md:col-span-4" label={t('common.comment')} value={form.comment} error={errors.comment} onChange={(e) => { set('comment', e.target.value) }} />
        </div>
      </Block>

      <section aria-label={t('orders.blockExtra')} className="space-y-2 rounded-card border border-line bg-surface p-4 shadow-card">
        <Button variant="ghost" aria-expanded={showExtra} onClick={() => { setExtraOpen(!showExtra) }}>
          {showExtra ? '▾' : '▸'} {t('orders.blockExtra')}
        </Button>
        {showExtra ? (
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          <TextField label={t('orders.contractNumber')} value={form.contract_number} error={errors.contract_number} onChange={(e) => { set('contract_number', e.target.value) }} />
          <TextField label={t('orders.clientRef')} value={form.client_ref} error={errors.client_ref} onChange={(e) => { set('client_ref', e.target.value) }} />
          <Select
            label={t('orders.contact')}
            value={form.contact}
            disabled={clientId === null}
            placeholder={t('common.none')}
            options={contacts.map((c) => ({ value: String(c.id), label: c.name }))}
            error={errors.contact}
            onChange={(v) => { set('contact', v) }}
          />
          {users.allowed ? (
            <>
              <Select label={t('orders.forwarder')} value={form.forwarder} placeholder={t('common.none')} options={userOptions} error={errors.forwarder} onChange={(v) => { set('forwarder', v) }} />
              <fieldset className="md:col-span-3">
                <legend className="mb-1 text-xs font-medium text-muted">{t('orders.extraManagers')}</legend>
                <div className="flex flex-wrap gap-x-4 gap-y-1">
                  {activeUsers.map((u) => (
                    <label key={u.user_id} className="flex items-center gap-1 text-sm">
                      <input
                        type="checkbox"
                        checked={form.extra_managers.includes(u.user_id)}
                        onChange={(event) => {
                          set('extra_managers', event.target.checked ? [...form.extra_managers, u.user_id] : form.extra_managers.filter((id) => id !== u.user_id))
                        }}
                      />
                      {userLabel(u)}
                    </label>
                  ))}
                </div>
                {errors.extra_managers ? <p className="text-xs text-red-600">{errors.extra_managers}</p> : null}
              </fieldset>
            </>
          ) : null}
          {transport.allowed ? (
            <Select label={t('orders.transportCondition')} value={form.transport_condition} placeholder={t('common.none')} options={selectableValues(transport.all, order?.transport_condition).map((v) => ({ value: String(v.id), label: v.name }))} error={errors.transport_condition} onChange={(v) => { set('transport_condition', v) }} />
          ) : null}
          <TextField label={t('orders.deliveryDays')} inputMode="numeric" value={form.delivery_days} error={errors.delivery_days} onChange={(e) => { set('delivery_days', e.target.value) }} />
          <TextField label={t('orders.paymentDelayDays')} inputMode="numeric" value={form.payment_delay_days} error={errors.payment_delay_days} onChange={(e) => { set('payment_delay_days', e.target.value) }} />
          {delay.allowed ? (
            <Select label={t('orders.paymentDelayCondition')} value={form.payment_delay_condition} placeholder={t('common.none')} options={selectableValues(delay.all, order?.payment_delay_condition).map((v) => ({ value: String(v.id), label: v.name }))} error={errors.payment_delay_condition} onChange={(v) => { set('payment_delay_condition', v) }} />
          ) : null}
          </div>
        ) : null}
      </section>

      {mode === 'create' ? (
        <>
          <Block title={t('orders.blockCargo')}>
            <p className="text-xs text-muted">{t('orders.cargoOptional')}</p>
            {errors.consignments ? <p role="alert" className="text-xs text-red-600">{errors.consignments}</p> : null}
            {form.consignments.map((c, index) => (
              <div key={c.key} className="space-y-2 rounded-control border border-line p-2">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-medium">{t('orders.cargoN', { n: index + 1 })}</h3>
                  <Button
                    variant="ghost"
                    aria-label={t('orders.removeCargoN', { n: index + 1 })}
                    onClick={() => { set('consignments', form.consignments.filter((_, i) => i !== index)) }}
                  >
                    {t('common.remove')}
                  </Button>
                </div>
                <CargoFields value={c} prefix={`consignments.${String(index)}.`} errors={errors} onChange={(next) => { setCargo(index, next) }} />
              </div>
            ))}
            <Button onClick={() => { set('consignments', [...form.consignments, emptyConsignment()]) }}>{t('orders.addCargo')}</Button>
          </Block>
          <Block title={t('orders.blockRoute')}>
            {form.consignments.length === 0 ? <p className="text-xs text-muted">{t('orders.routeNeedsCargo')}</p> : null}
            {form.consignments.map((c, index) => (
              <div key={c.key} className="space-y-2">
                <h3 className="text-sm font-medium">{t('orders.cargoN', { n: index + 1 })}{c.name ? `: ${c.name}` : ''}</h3>
                <RouteFields value={c} prefix={`consignments.${String(index)}.`} errors={errors} onChange={(next) => { setCargo(index, next) }} />
              </div>
            ))}
          </Block>
        </>
      ) : null}

      <div className="flex justify-end gap-2">
        <Button onClick={onCancel} disabled={submitting}>{t('common.cancel')}</Button>
        <WriteButton type="submit" variant="primary" permission={mode === 'create' ? 'orders.create' : 'orders.update'} disabled={submitting}>
          {submitting ? t('common.saving') : t('common.save')}
        </WriteButton>
      </div>
    </form>
  )
}
