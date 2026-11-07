import { useTranslation } from 'react-i18next'
import { useFormat } from '../../shared/format/useFormat'
import type { DebtsExcluded, RealizedSummary } from './types'

const REASONS = ['no_rate', 'prior_base', 'no_base_rate'] as const
const KEYS = { no_rate: 'noRate', prior_base: 'priorBase', no_base_rate: 'noBaseRate' } as const

/**
 * Пометка неполноты показателей долга в базовой валюте (1.4.14): сколько счетов не вошло в итоги
 * базы или без нереализованной разницы и почему. Суммы - в исходной валюте, в подсказке (title) и
 * в скрытом тексте для скринридеров. Ничего не рисует, если исключений нет.
 */
export function DebtsExcludedHint({ excluded, className }: { excluded: DebtsExcluded | null | undefined; className?: string }) {
  const { t } = useTranslation()
  const { money } = useFormat()
  if (!excluded || excluded.count === 0) return null
  const lines = REASONS.filter((reason) => excluded[reason].count > 0).map((reason) => {
    const part = excluded[reason]
    const sums = Object.entries(part.by_currency)
      .map(([code, v]) => `${money(v.open, code)}${reason === 'prior_base' ? ` (${t('finance.fx.equivalentRef')} ${money(v.equivalent_base)})` : ''}`)
      .join('; ')
    return `${t(`finance.fx.excluded.${KEYS[reason]}`, { count: part.count })}: ${sums}`
  })
  return (
    <p className={className ?? 'text-xs text-amber-700 dark:text-amber-300'} title={lines.join('\n')}>
      {t('finance.fx.excluded.summary', { count: excluded.count })}
      <span className="sr-only"> {lines.join('. ')}</span>
    </p>
  )
}

/** То же для реализованной курсовой разницы по оплатам: оплаты без базового курса или в прежней базе. */
export function RealizedExcludedHint({ summary, className }: { summary: RealizedSummary | undefined; className?: string }) {
  const { t } = useTranslation()
  const { money } = useFormat()
  if (!summary?.is_partial) return null
  const lines = (['prior_base', 'no_base_rate'] as const)
    .filter((reason) => summary.excluded[reason].count > 0)
    .map((reason) => {
      const part = summary.excluded[reason]
      const sums = Object.entries(part.by_currency).map(([code, v]) => money(v, code)).join('; ')
      return `${t(`finance.fx.excluded.${KEYS[reason]}Payments`, { count: part.count })}: ${sums}`
    })
  return (
    <p className={className ?? 'text-xs text-amber-700 dark:text-amber-300'} title={lines.join('\n')}>
      {t('finance.fx.excluded.paymentsSummary', { count: summary.excluded.count })}
      <span className="sr-only"> {lines.join('. ')}</span>
    </p>
  )
}
