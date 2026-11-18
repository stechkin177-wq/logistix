import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { codecs, useUrlState } from '../../shared/hooks/useUrlState'
import { Tabs } from '../../shared/ui/Tabs'
import { PeriodPicker } from '../dashboard/PeriodPicker'
import { FinanceSummaryCards } from './FinanceSummaryCards'
import { DebtsTab } from './DebtsTab'
import { ExpensesTab } from './ExpensesTab'
import { IncomesTab } from './IncomesTab'
import { useFinanceEngine } from './ledgerHooks'
import { InvoicesTab } from './InvoicesTab'
import { OperationsTab } from './OperationsTab'
import { PaymentsTab } from './PaymentsTab'
import { RatesTab } from './RatesTab'
import { PageHeader } from '../../shared/ui/PageHeader'
import { ChartColumn, ClipboardList, Coins, CreditCard, ReceiptText, Scale, TrendingDown, TrendingUp, Wallet, type LucideIcon } from '../../shared/ui/icons'

const TAB_KEYS = ['analytics', 'invoices', 'payments', 'operations', 'debts', 'rates', 'incomes', 'expenses'] as const
/** Доходы и расходы показываются только при engine = new. */
const NEW_ONLY: TabKey[] = ['incomes', 'expenses']
type TabKey = (typeof TAB_KEYS)[number]

const PANELS: Record<TabKey, () => ReactNode> = {
  analytics: () => <FinanceSummaryCards withFx />,
  invoices: () => <InvoicesTab />,
  payments: () => <PaymentsTab />,
  operations: () => <OperationsTab />,
  debts: () => <DebtsTab />,
  rates: () => <RatesTab />,
  incomes: () => <IncomesTab />,
  expenses: () => <ExpensesTab />,
}

const TAB_ICONS: Record<TabKey, LucideIcon> = {
  analytics: ChartColumn, invoices: ReceiptText, payments: CreditCard, operations: ClipboardList, debts: Scale, rates: Coins, incomes: TrendingUp, expenses: TrendingDown,
}

const SCHEMA = { tab: codecs.oneOf(TAB_KEYS, 'analytics') }

/** Финансы: вкладки раздела; выбранная вкладка хранится в адресе (?tab=). */
export function FinancePage() {
  const { t } = useTranslation()
  const [state, setState] = useUrlState(SCHEMA)
  const { engine } = useFinanceEngine()
  const visible = TAB_KEYS.filter((key) => engine === 'new' || !NEW_ONLY.includes(key))
  const active: TabKey = visible.includes(state.tab) ? state.tab : 'analytics'
  return (
    <div className="space-y-3">
      <PageHeader icon={Wallet} title={t('nav.finance')} hint="finance" actions={active === 'analytics' ? <PeriodPicker /> : undefined} />
      <Tabs
        label={t('finance.tabsLabel')}
        active={active}
        variant="pills" pinned
        tabs={visible.map((key) => ({ key, label: t(`finance.tabs.${key}`), icon: TAB_ICONS[key] }))}
        onChange={(tab) => { setState({ tab: tab as TabKey }) }}
      />
      <div role="tabpanel" id={`panel-${active}`} aria-labelledby={`tab-${active}`}>
        {PANELS[active]()}
      </div>
    </div>
  )
}
