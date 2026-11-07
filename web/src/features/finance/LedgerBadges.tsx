import { useTranslation } from 'react-i18next'
import { Badge, type Tone } from '../../shared/ui/Badge'
import type { ExpenseRow, IncomeRow } from './ledgerTypes'

const INCOME_TONE: Record<IncomeRow['status'], Tone> = { planned: 'info', recognized: 'success', void: 'neutral' }

export function IncomeStatusBadge({ status }: { status: IncomeRow['status'] }) {
  const { t } = useTranslation()
  return <Badge tone={INCOME_TONE[status]}>{t(`finance.ledger.incomeStatus.${status}`)}</Badge>
}

export function ExpenseStatusBadge({ status }: { status: ExpenseRow['status'] }) {
  const { t } = useTranslation()
  return <Badge tone={status === 'active' ? 'success' : 'neutral'}>{t(`finance.ledger.expenseStatus.${status}`)}</Badge>
}

/** Метка «нужна проверка» с причиной (расхождение со счётом и т. п.). */
export function ReviewBadge({ expense }: { expense: Pick<ExpenseRow, 'needs_review' | 'review_reason' | 'invoice_variance'> }) {
  const { t } = useTranslation()
  if (!expense.needs_review) return null
  const reason = expense.review_reason ? t(`finance.ledger.reviewReason.${expense.review_reason}`, { defaultValue: expense.review_reason }) : ''
  const variance = expense.invoice_variance && expense.review_reason === 'invoice_variance'
    ? ` (${t('finance.ledger.variance')}: ${expense.invoice_variance})`
    : ''
  return <Badge tone="warning" title={reason}>{t('finance.ledger.needsReview')}{variance}</Badge>
}
