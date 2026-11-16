import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { DashboardSummary } from '../../shared/api/types'
import { useFormat } from '../../shared/format/useFormat'
import { Button } from '../../shared/ui/Button'
import { DateInput } from '../../shared/ui/DateInput'
import { SlidersHorizontal } from '../../shared/ui/icons'
import { Stat } from '../../shared/ui/Stat'
import { DEFAULT_PERIOD, type ProfitPeriod, type ProfitPreset } from './profitPeriod'

const PRESETS: ProfitPreset[] = ['month', 'prev_month', 'quarter', 'year', 'custom']
const ruDate = (iso: string) => iso.split('-').reverse().join('.')

/** Плитка прибыли: сумма, маржа мелким текстом под ней и настройка периода (месяц, квартал, год или свой диапазон). */
export function ProfitTile({ data, period, onChange }: { data: DashboardSummary; period: ProfitPeriod; onChange: (next: ProfitPeriod) => void }) {
  const { t } = useTranslation()
  const { money } = useFormat()
  const [open, setOpen] = useState(false)
  const [from, setFrom] = useState(period.from ?? '')
  const [to, setTo] = useState(period.to ?? '')
  const root = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (event: MouseEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const customValid = from !== '' && to !== '' && from <= to
  const margin = data.month_margin_pct === null ? null : t('dashboard.marginInline', { value: money(data.month_margin_pct) })
  const dates = period.preset !== 'month' && data.profit_from && data.profit_to ? `${ruDate(data.profit_from)} – ${ruDate(data.profit_to)}` : null
  const sub = margin || dates ? (
    <>
      {margin}
      {margin && dates ? <br /> : null}
      {dates}
    </>
  ) : null

  return (
    <div ref={root} className="relative h-full w-full">
      <Stat
        label={t(`dashboard.profitLabel.${period.preset}`)}
        value={money(data.month_profit, data.currency ?? undefined)}
        sub={sub}
        action={
          <button
            type="button"
            aria-expanded={open}
            aria-label={t('dashboard.periodConfigure')}
            title={t('dashboard.periodConfigure')}
            onClick={() => { setOpen(!open) }}
            className="inline-flex size-6 items-center justify-center rounded-md text-muted hover:bg-surface hover:text-ink"
          >
            <SlidersHorizontal className="size-3.5" aria-hidden="true" />
          </button>
        }
      />
      {open ? (
        <div role="dialog" aria-label={t('dashboard.periodTitle')} className="absolute left-0 top-full z-30 mt-2 w-72 max-w-[calc(100vw-2rem)] space-y-3 rounded-card border border-line bg-surface p-3 shadow-pop">
          <p className="text-sm font-semibold">{t('dashboard.periodTitle')}</p>
          <div className="space-y-0.5">
            {PRESETS.map((preset) => (
              <button
                key={preset}
                type="button"
                aria-pressed={period.preset === preset}
                onClick={() => {
                  if (preset === 'custom') onChange({ preset: 'custom', from: from || undefined, to: to || undefined })
                  else { onChange({ preset }); setOpen(false) }
                }}
                className={`flex w-full items-center rounded-control px-2.5 py-1.5 text-left text-sm ${period.preset === preset ? 'bg-brand-50 font-medium text-brand-700 dark:bg-brand-900/50 dark:text-brand-100' : 'hover:bg-surface-2'}`}
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
              <Button
                variant="primary"
                className="w-full"
                disabled={!customValid}
                onClick={() => { onChange({ preset: 'custom', from, to }); setOpen(false) }}
              >
                {t('dashboard.periodApply')}
              </Button>
            </div>
          ) : null}
          {period.preset !== DEFAULT_PERIOD.preset ? (
            <button type="button" className="text-xs text-muted underline hover:text-ink" onClick={() => { onChange(DEFAULT_PERIOD); setOpen(false) }}>
              {t('dashboard.periodReset')}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
