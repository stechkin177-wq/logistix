import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../../shared/api/errors'
import { useConsignmentListSearch } from './useCargoSearch'
import { Banner } from '../../../shared/ui/Banner'
import { Button } from '../../../shared/ui/Button'
import { Checkbox } from '../../../shared/ui/Checkbox'
import { Drawer } from '../../../shared/ui/Drawer'
import { TextField } from '../../../shared/ui/TextField'
import { WriteButton } from '../../../shared/ui/WriteButton'
import { useReassignTrip } from '../hooks'
import type { Trip, TripCargo } from '../types'

/** Изменение набора грузов рейса (POST /trips/{id}/reassign/): текущие грузы + поиск других. Нужен хотя бы один. */
export function ReassignDrawer({ trip, onClose }: { trip: Trip; onClose: () => void }) {
  const { t } = useTranslation()
  const [chosen, setChosen] = useState<Map<number, TripCargo>>(() => new Map(trip.consignments.map((c) => [c.id, c])))
  const [q, setQ] = useState('')
  const [error, setError] = useState<string | undefined>()
  const reassign = useReassignTrip()
  const search = useConsignmentListSearch(q)

  const toggle = (c: TripCargo) => {
    setChosen((prev) => {
      const next = new Map(prev)
      if (next.has(c.id)) next.delete(c.id)
      else next.set(c.id, c)
      return next
    })
  }

  const submit = () => {
    if (chosen.size === 0) {
      setError(t('trips.needCargo'))
      return
    }
    setError(undefined)
    reassign.mutate(
      { id: trip.id, ids: [...chosen.keys()] },
      { onSuccess: onClose, onError: (e) => { setError(errorMessage(e, t)) } },
    )
  }

  // строки не исчезают при снятии флажка (можно вернуть); добавленные из поиска остаются в списке
  const listed = [...trip.consignments, ...[...chosen.values()].filter((c) => !trip.consignments.some((own) => own.id === c.id))]
  const found: TripCargo[] = (search.data?.results ?? [])
    .filter((c) => !listed.some((own) => own.id === c.id))
    .map((c) => ({ id: c.id, name: c.name, order: c.order, order_number: c.order_number }))

  return (
    <Drawer
      open
      title={t('trips.reassignTitle', { number: trip.number })}
      onClose={onClose}
      busy={reassign.isPending}
      footer={
        <>
          <Button onClick={onClose} disabled={reassign.isPending}>{t('common.cancel')}</Button>
          <WriteButton permission="trips.update" variant="primary" onClick={submit} disabled={reassign.isPending}>
            {reassign.isPending ? t('common.saving') : t('common.save')}
          </WriteButton>
        </>
      }
    >
      <div className="space-y-3">
        <Banner kind="info">{t('trips.numberNeverChanges')}</Banner>
        {error ? <Banner kind="error">{error}</Banner> : null}
        <section aria-labelledby="reassign-current">
          <h3 id="reassign-current" className="mb-1 text-xs font-medium">{t('trips.cargoInTrip', { count: chosen.size })}</h3>
          <ul className="divide-y divide-slate-100 rounded border border-slate-200 dark:divide-slate-800 dark:border-slate-700">
            {listed.map((c) => (
              <li key={c.id} className="px-2">
                <Checkbox checked={chosen.has(c.id)} label={`${c.name} (${c.order_number})`} onChange={() => { toggle(c) }} />
              </li>
            ))}
          </ul>
        </section>
        <section aria-labelledby="reassign-search" className="space-y-1">
          <h3 id="reassign-search" className="text-xs font-medium">{t('trips.addCargo')}</h3>
          <TextField label={t('common.search')} type="search" placeholder={t('consignments.searchPlaceholder')} value={q} onChange={(e) => { setQ(e.target.value) }} />
          {search.isError ? <Banner kind="error">{errorMessage(search.error, t)}</Banner> : null}
          <ul className="divide-y divide-slate-100 rounded border border-slate-200 dark:divide-slate-800 dark:border-slate-700">
            {found.length === 0 ? (
              <li className="px-2 py-1 text-xs text-slate-500">{search.isFetching ? t('combobox.loading') : t('common.noResults')}</li>
            ) : (
              found.map((c) => (
                <li key={c.id} className="px-2">
                  <Checkbox checked={chosen.has(c.id)} label={`${c.name} (${c.order_number})`} onChange={() => { toggle(c) }} />
                </li>
              ))
            )}
          </ul>
        </section>
      </div>
    </Drawer>
  )
}
