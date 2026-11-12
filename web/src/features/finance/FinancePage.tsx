import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { codecs, useUrlState } from '../../shared/hooks/useUrlState'
import { Tabs } from '../../shared/ui/Tabs'
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
import { Wallet } from '../../shared/ui/icons'

const TAB_KEYS = ['invoices', 'payments', 'operations', 'debts', 'rates', 'incomes', 'expenses'] as const
/** Доходы и расходы показываются только при engine = new. */
const NEW_ONLY: TabKey[] = ['incomes', 'expenses']
type TabKey = (typeof TAB_KEYS)[number]

const PANELS: Record<TabKey, () => ReactNode> = {
  invoices: () => <InvoicesTab />,
  payments: () => <PaymentsTab />,
  operations: () => <OperationsTab />,
  debts: () => <DebtsTab />,
  rates: () => <RatesTab />,
  incomes: () => <IncomesTab />,
  expenses: () => <ExpensesTab />,
}

const SCHEMA = { tab: codecs.oneOf(TAB_KEYS, 'invoices') }

/** Финансы: вкладки раздела; выбранная вкладка хранится в адресе (?tab=). */
export function FinancePage() {
  const { t } = useTranslation()
  const [state, setState] = useUrlState(SCHEMA)
  const { engine } = useFinanceEngine()
  const visible = TAB_KEYS.filter((key) => engine === 'new' || !NEW_ONLY.includes(key))
  const active: TabKey = visible.includes(state.tab) ? state.tab : 'invoices'
  return (
    <div className="space-y-3">
      <PageHeader icon={Wallet} title={t('nav.finance')} />
      <FinanceSummaryCards />
      <Tabs
        label={t('finance.tabsLabel')}
        active={active}
        tabs={visible.map((key) => ({ key, label: t(`finance.tabs.${key}`) }))}
        onChange={(tab) => { setState({ tab: tab as TabKey }) }}
      />
      <div role="tabpanel" id={`panel-${active}`} aria-labelledby={`tab-${active}`}>
        {PANELS[active]()}
      </div>
    </div>
  )
}
