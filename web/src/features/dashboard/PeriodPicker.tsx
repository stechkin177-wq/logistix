import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '../../shared/ui/Button'
import { DateInput } from '../../shared/ui/DateInput'
import { Filter } from '../../shared/ui/icons'
import { DEFAULT_PERIOD, usePeriod, type ProfitPreset } from './profitPeriod'

const PRESETS: ProfitPreset[] = ['month', 'prev_month', 'quarter', 'year', 'custom']

/**
 * Выбор периода для всех финансовых показателей (дашборд и «Финансы»): значок-фильтр с названием периода;
 * по нажатию - текущий месяц, прошлый месяц, квартал, год или свой диапазон.
 */
export function PeriodPicker() {
  const { t } = useTranslation()
  const [period, setPeriod] = usePeriod()
  const [open, setOpen] = useState(false)
  const [from, setFrom] = useState(period.from ?? '')
  const [to, setTo] = useState(period.to ?? '')
  const root = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (event: MouseEvent) => { if (root.current && !root.current.contains(event.target as Node)) setOpen(false) }
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey) }
  }, [open])

  const customValid = from !== '' && to !== '' && from <= to
  return (
    <div ref={root} className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={t('dashboard.periodConfigure')}
        title={t('dashboard.periodConfigure')}
        onClick={() => { setOpen(!open) }}
        className={`inline-flex h-9 items-center gap-2 rounded-control border px-3 text-sm font-medium shadow-sm transition-colors ${period.preset === 'month' ? 'border-line bg-surface text-ink hover:bg-surface-2' : 'border-brand-300 bg-brand-50 text-brand-700 dark:border-line dark:bg-white/10 dark:text-brand-100'}`}
      >
        <Filter className="size-4" aria-hidden="true" />
        <span className="max-sm:sr-only">{t(`dashboard.periodPreset.${period.preset}`)}</span>
      </button>
      {open ? (
        <div role="dialog" aria-label={t('dashboard.periodTitle')} className="absolute right-0 top-full z-30 mt-2 w-72 max-w-[calc(100vw-2rem)] space-y-3 rounded-card border border-line bg-surface p-3 shadow-pop">
          <p className="text-sm font-semibold">{t('dashboard.periodTitle')}</p>
          <div className="space-y-0.5">
            {PRESETS.map((preset) => (
              <button
                key={preset}
                type="button"
                aria-pressed={period.preset === preset}
                onClick={() => {
                  if (preset === 'custom') setPeriod({ preset: 'custom', from: from || undefined, to: to || undefined })
                  else { setPeriod({ preset }); setOpen(false) }
                }}
                className={`flex w-full items-center rounded-control px-2.5 py-1.5 text-left text-sm ${period.preset === preset ? 'bg-brand-50 font-medium text-brand-700 dark:bg-white/10 dark:text-brand-100' : 'hover:bg-surface-2'}`}
              >
                {t(`dashboard.periodPreset.${preset}`)}
              </button>
            ))}
          </div>
          {period.preset === 'custom' ? (
            <div className="space-y-2 border-t border-line pt-3">
              <div className="grid grid-cols-2 gap-2">
                <DateInput label={t('dashboard.periodFrom')} value={from} onChange={setFrom} />
                <DateInput label={t('dashboard.periodTo')} value={to} onChange={setTo} />
              </div>
              <Button variant="primary" className="w-full" disabled={!customValid} onClick={() => { setPeriod({ preset: 'custom', from, to }); setOpen(false) }}>
                {t('dashboard.periodApply')}
              </Button>
            </div>
          ) : null}
          {period.preset !== DEFAULT_PERIOD.preset ? (
            <button type="button" className="text-xs text-muted underline hover:text-ink" onClick={() => { setPeriod(DEFAULT_PERIOD); setOpen(false) }}>
              {t('dashboard.periodReset')}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
