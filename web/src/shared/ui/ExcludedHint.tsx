import { useTranslation } from 'react-i18next'
import type { ExcludedBase, ExcludedPart } from '../api/types'
import { useFormat } from '../format/useFormat'

/** Суммы части по валютам: «KZT: доход 1 000,00 / расход 300,00; USD: ...» (для подсказки). */
function amounts(part: ExcludedPart, money: (v: string, c?: string) => string, label: (k: 'income' | 'expense') => string) {
  return Object.entries(part.by_currency)
    .map(([code, v]) => [
      code,
      ...(Number(v.income) !== 0 ? [`${label('income')} ${money(v.income, code)}`] : []),
      ...(Number(v.expense) !== 0 ? [`${label('expense')} ${money(v.expense, code)}`] : []),
    ].join(' '))
    .join('; ')
}

/**
 * Компактная пометка неполноты итога в базовой валюте: сколько записей не вошло и почему.
 * Подробные суммы (в исходной валюте, без пересчёта задним числом) - в подсказке (title) и
 * в скрытом тексте для скринридеров. Ничего не рисует, если исключений нет.
 */
export function ExcludedHint({ excluded, className }: { excluded: ExcludedBase | null | undefined; className?: string }) {
  const { t } = useTranslation()
  const { money } = useFormat()
  if (!excluded || excluded.count === 0) return null
  const label = (k: 'income' | 'expense') => t(`finance.excluded.${k}`)
  const lines = [
    excluded.prior_base.count > 0
      ? `${t('finance.excluded.priorBase', { count: excluded.prior_base.count })}: ${amounts(excluded.prior_base, money, label)}`
      : '',
    excluded.no_rate.count > 0
      ? `${t('finance.excluded.noRate', { count: excluded.no_rate.count })}: ${amounts(excluded.no_rate, money, label)}`
      : '',
  ].filter(Boolean)
  return (
    <p className={className ?? 'text-xs text-amber-700 dark:text-amber-300'} title={lines.join('\n')}>
      {t('finance.excluded.summary', { count: excluded.count, orders: excluded.orders })}
      <span className="sr-only"> {lines.join('. ')}</span>
    </p>
  )
}
