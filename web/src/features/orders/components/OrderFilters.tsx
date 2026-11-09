import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '../../../shared/ui/Button'
import { Combobox } from '../../../shared/ui/Combobox'
import { DateInput } from '../../../shared/ui/DateInput'
import { FilterBar, FilterItem } from '../../../shared/ui/FilterBar'
import { TextField } from '../../../shared/ui/TextField'
import { searchCarriers } from '../../carriers/api'
import { searchClients } from '../../clients/api'
import { useOrderStatuses, usePartyOption } from '../hooks'
import type { OrderListFilters } from '../types'

export const EMPTY_FILTERS: OrderListFilters = {
  q: '', status: [], client: null, carrier: null, loading_from: '', loading_to: '', created_from: '', created_to: '',
  completed_from: '', completed_to: '', unassigned: false,
}

export function hasFilters(f: OrderListFilters): boolean {
  return JSON.stringify({ ...f }) !== JSON.stringify(EMPTY_FILTERS)
}

/** Сколько дополнительных (скрытых по умолчанию) фильтров заполнено. */
export function extraFiltersCount(f: OrderListFilters): number {
  const keys = ['carrier', 'loading_from', 'loading_to', 'created_from', 'created_to', 'completed_from', 'completed_to'] as const
  return keys.filter((k) => f[k] !== EMPTY_FILTERS[k]).length + (f.unassigned ? 1 : 0)
}

interface Props {
  value: OrderListFilters
  onChange: (patch: Partial<OrderListFilters>, opts?: { replace?: boolean }) => void
  actions?: React.ReactNode
}

/** Полный набор фильтров заказов; состояние живёт в URL (useUrlState), поэтому ссылка воспроизводит выборку. */
export function OrderFilters({ value, onChange, actions }: Props) {
  const { t } = useTranslation()
  const { statuses } = useOrderStatuses()
  const client = usePartyOption('clients', value.client)
  const carrier = usePartyOption('carriers', value.carrier)
  const extraCount = extraFiltersCount(value)
  const [more, setMore] = useState(false)
  const showMore = more || extraCount > 0

  return (
    <FilterBar
      canReset={hasFilters(value)}
      onReset={() => { onChange(EMPTY_FILTERS) }}
      actions={actions}
    >
      <FilterItem className="w-48">
        <TextField label={t('common.search')} type="search" placeholder={t('orders.searchPlaceholder')} value={value.q} onChange={(e) => { onChange({ q: e.target.value }, { replace: true }) }} />
      </FilterItem>
      <FilterItem className="w-44">
        <details className="relative">
          <summary className="flex h-8 cursor-pointer items-center rounded border border-slate-300 bg-white px-2 text-sm dark:border-slate-600 dark:bg-slate-900">
            {t('orders.statusFilter')}
            {value.status.length ? ` (${String(value.status.length)})` : ''}
          </summary>
          <fieldset className="absolute z-20 mt-1 max-h-64 w-56 overflow-auto rounded border border-slate-200 bg-white p-2 shadow dark:border-slate-700 dark:bg-slate-900">
            <legend className="sr-only">{t('orders.statusFilter')}</legend>
            {statuses.map((s) => (
              <label key={s.id} className="flex items-center gap-2 py-0.5 text-sm">
                <input
                  type="checkbox"
                  checked={value.status.includes(s.id)}
                  onChange={(event) => {
                    onChange({ status: event.target.checked ? [...value.status, s.id] : value.status.filter((id) => id !== s.id) })
                  }}
                />
                {s.name}
              </label>
            ))}
          </fieldset>
        </details>
      </FilterItem>
      <FilterItem className="w-44">
        <Combobox label={t('orders.client')} queryKey={['clients', 'search']} fetchOptions={searchClients} value={client} onChange={(o) => { onChange({ client: o?.id ?? null }) }} />
      </FilterItem>
      <Button
        variant="ghost"
        aria-expanded={showMore}
        onClick={() => { setMore(!showMore) }}
      >
        {t('orders.moreFilters')}{extraCount ? ` (${String(extraCount)})` : ''}
      </Button>
      {showMore ? (
        <>
      <FilterItem className="w-44">
        <Combobox label={t('orders.carrier')} queryKey={['carriers', 'search']} fetchOptions={searchCarriers} value={carrier} onChange={(o) => { onChange({ carrier: o?.id ?? null }) }} />
      </FilterItem>
      <FilterItem className="w-36"><DateInput label={t('orders.loadingFrom')} value={value.loading_from} onChange={(v) => { onChange({ loading_from: v }) }} /></FilterItem>
      <FilterItem className="w-36"><DateInput label={t('orders.loadingTo')} value={value.loading_to} onChange={(v) => { onChange({ loading_to: v }) }} /></FilterItem>
      <FilterItem className="w-36"><DateInput label={t('orders.createdFrom')} value={value.created_from} onChange={(v) => { onChange({ created_from: v }) }} /></FilterItem>
      <FilterItem className="w-36"><DateInput label={t('orders.createdTo')} value={value.created_to} onChange={(v) => { onChange({ created_to: v }) }} /></FilterItem>
      <FilterItem className="w-36"><DateInput label={t('orders.completedFrom')} value={value.completed_from} onChange={(v) => { onChange({ completed_from: v }) }} /></FilterItem>
      <FilterItem className="w-36"><DateInput label={t('orders.completedTo')} value={value.completed_to} onChange={(v) => { onChange({ completed_to: v }) }} /></FilterItem>
      <label className="flex h-8 items-center gap-1 text-sm">
        <input type="checkbox" checked={value.unassigned} onChange={(event) => { onChange({ unassigned: event.target.checked }) }} />
        {t('orders.unassigned')}
      </label>
        </>
      ) : null}
    </FilterBar>
  )
}
