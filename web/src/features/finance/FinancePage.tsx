import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { codecs, useUrlState } from '../../shared/hooks/useUrlState'
import { Tabs } from '../../shared/ui/Tabs'
import { InvoicesTab } from './InvoicesTab'
import { PaymentsTab } from './PaymentsTab'
import { RatesTab } from './RatesTab'

const TAB_KEYS = ['invoices', 'payments', 'rates'] as const
type TabKey = (typeof TAB_KEYS)[number]

const PANELS: Record<TabKey, () => ReactNode> = {
  invoices: () => <InvoicesTab />,
  payments: () => <PaymentsTab />,
  rates: () => <RatesTab />,
}

const SCHEMA = { tab: codecs.oneOf(TAB_KEYS, 'invoices') }

/** Финансы: вкладки раздела; выбранная вкладка хранится в адресе (?tab=). */
export function FinancePage() {
  const { t } = useTranslation()
  const [state, setState] = useUrlState(SCHEMA)
  return (
    <div className="space-y-3">
      <h1 className="text-base font-semibold">{t('nav.finance')}</h1>
      <Tabs
        label={t('finance.tabsLabel')}
        active={state.tab}
        tabs={TAB_KEYS.map((key) => ({ key, label: t(`finance.tabs.${key}`) }))}
        onChange={(tab) => { setState({ tab: tab as TabKey }) }}
      />
      <div role="tabpanel" id={`panel-${state.tab}`} aria-labelledby={`tab-${state.tab}`}>
        {PANELS[state.tab]()}
      </div>
    </div>
  )
}
