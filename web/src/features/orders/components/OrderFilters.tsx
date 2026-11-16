import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '../../../shared/ui/Button'
import { Checkbox } from '../../../shared/ui/Checkbox'
import { Combobox } from '../../../shared/ui/Combobox'
import { DateInput } from '../../../shared/ui/DateInput'
import { FilterBar, FilterItem } from '../../../shared/ui/FilterBar'
import { TextField } from '../../../shared/ui/TextField'
import { searchCarriers } from '../../carriers/api'
import { Select } from '../../../shared/ui/Select'
import { useLabels } from '../../labels/hooks'
import { searchClients } from '../../clients/api'
import { useOrderStatuses, usePartyOption } from '../hooks'
import { ChevronDown } from '../../../shared/ui/icons'
import type { OrderListFilters } from '../types'

export const EMPTY_FILTERS: OrderListFilters = {
  q: '', status: [], client: null, carrier: null, label: null, loading_from: '', loading_to: '', created_from: '', created_to: '',
  completed_from: '', completed_to: '', unassigned: false,
}

export function hasFilters(f: OrderListFilters): boolean {
  return JSON.stringify({ ...f }) !== JSON.stringify(EMPTY_FILTERS)
}

/** Сколько дополнительных (скрытых по умолчанию) фильтров заполнено. */
export function extraFiltersCount(f: OrderListFilters): number {
  const keys = ['loading_from', 'loading_to', 'created_from', 'created_to', 'completed_from', 'completed_to'] as const
  return keys.filter((k) => f[k] !== EMPTY_FILTERS[k]).length + (f.unassigned ? 1 : 0)
}

type StatusItem = ReturnType<typeof useOrderStatuses>['statuses'][number]

/** Выпадающий список статусов с галочками: порядок как в справочнике, «в работе» → «завершённые»; закрывается по клику вне и Esc. */
function StatusFilter({ statuses, value, onChange }: { statuses: StatusItem[]; value: number[]; onChange: (ids: number[]) => void }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent | TouchEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('touchstart', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('touchstart', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])
  const groups = useMemo(() => {
    const visible = statuses.filter((s) => s.isActive || value.includes(s.id)).sort((a, b) => a.order - b.order || a.id - b.id)
    return [
      { key: 'work', title: t('orders.statusGroupWork'), items: visible.filter((s) => !s.isFinal) },
      { key: 'done', title: t('orders.statusGroupDone'), items: visible.filter((s) => s.isFinal) },
    ].filter((g) => g.items.length > 0)
  }, [statuses, value, t])
  const toggle = (id: number, on: boolean) => { onChange(on ? [...value, id] : value.filter((x) => x !== id)) }
  return (
    <div ref={box} className="relative">
      <button
        type="button"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => { setOpen(!open) }}
        className="flex h-9 w-full items-center justify-between gap-2 rounded-control border border-line bg-surface px-3 text-sm"
      >
        <span className="truncate">{t('orders.statusFilter')}{value.length ? ` (${String(value.length)})` : ''}</span>
        <ChevronDown className="size-4 shrink-0 text-muted" aria-hidden="true" />
      </button>
      {open ? (
        <fieldset className="absolute left-0 z-30 mt-1 max-h-72 w-60 overflow-auto rounded-control border border-line bg-surface p-1.5 shadow-pop">
          <legend className="sr-only">{t('orders.statusFilter')}</legend>
          {groups.map((g) => (
            <div key={g.key} className="pb-1">
              <div className="px-1.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-muted">{g.title}</div>
              {g.items.map((s) => (
                <Checkbox key={s.id} className="flex w-full rounded px-1.5 hover:bg-surface-2" label={s.name} checked={value.includes(s.id)} onChange={(e) => { toggle(s.id, e.target.checked) }} />
              ))}
            </div>
          ))}
          {value.length ? (
            <button type="button" className="mt-1 w-full rounded px-1.5 py-1 text-left text-xs text-brand-700 hover:underline dark:text-brand-300" onClick={() => { onChange([]) }}>{t('common.reset')}</button>
          ) : null}
        </fieldset>
      ) : null}
    </div>
  )
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
  const labels = useLabels()
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
        <Combobox label={t('orders.client')} queryKey={['clients', 'search']} fetchOptions={searchClients} value={client} onChange={(o) => { onChange({ client: o?.id ?? null }) }} />
      </FilterItem>
      <FilterItem className="w-44">
        <Combobox label={t('orders.carrier')} queryKey={['carriers', 'search']} fetchOptions={searchCarriers} value={carrier} onChange={(o) => { onChange({ carrier: o?.id ?? null }) }} />
      </FilterItem>
      <FilterItem className="w-44">
        <StatusFilter statuses={statuses} value={value.status} onChange={(status) => { onChange({ status }) }} />
      </FilterItem>
      <FilterItem className="w-40">
        <Select label={t('labels.filter')} value={value.label === null ? '' : String(value.label)} placeholder={t('common.all')} options={(labels.data ?? []).map((l) => ({ value: String(l.id), label: l.name }))} onChange={(v) => { onChange({ label: v ? Number(v) : null }) }} />
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
      <FilterItem className="w-36"><DateInput label={t('orders.loadingFrom')} value={value.loading_from} onChange={(v) => { onChange({ loading_from: v }) }} /></FilterItem>
      <FilterItem className="w-36"><DateInput label={t('orders.loadingTo')} value={value.loading_to} onChange={(v) => { onChange({ loading_to: v }) }} /></FilterItem>
      <FilterItem className="w-36"><DateInput label={t('orders.createdFrom')} value={value.created_from} onChange={(v) => { onChange({ created_from: v }) }} /></FilterItem>
      <FilterItem className="w-36"><DateInput label={t('orders.createdTo')} value={value.created_to} onChange={(v) => { onChange({ created_to: v }) }} /></FilterItem>
      <FilterItem className="w-36"><DateInput label={t('orders.completedFrom')} value={value.completed_from} onChange={(v) => { onChange({ completed_from: v }) }} /></FilterItem>
      <FilterItem className="w-36"><DateInput label={t('orders.completedTo')} value={value.completed_to} onChange={(v) => { onChange({ completed_to: v }) }} /></FilterItem>
      <Checkbox className="h-9" label={t('orders.unassigned')} checked={value.unassigned} onChange={(event) => { onChange({ unassigned: event.target.checked }) }} />
        </>
      ) : null}
    </FilterBar>
  )
}
