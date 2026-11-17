import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { PageHeader } from '../../shared/ui/PageHeader'
import { Tabs } from '../../shared/ui/Tabs'
import { CreditCard, History, Landmark, Settings } from '../../shared/ui/icons'

export type ManageTab = 'companies' | 'plans' | 'history'

const TABS = [
  { key: 'companies', icon: Landmark },
  { key: 'plans', icon: CreditCard },
  { key: 'history', icon: History },
] as const

/** Шапка раздела «Управление» платформой - как в «Финансах»: название и три вкладки (подписки, тарифы, история изменений). */
export function ManageHeader({ active, actions }: { active: ManageTab; actions?: ReactNode }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  return (
    <>
      <PageHeader icon={Settings} title={t('platform.manage.title')} actions={actions} />
      <Tabs
        label={t('platform.manage.tabsLabel')}
        active={active}
        variant="pills"
        pinned
        tabs={TABS.map((tab) => ({ key: tab.key, icon: tab.icon, label: t(`platform.manage.tabs.${tab.key}`) }))}
        onChange={(key) => { void navigate(`/platform/${key}`) }}
      />
    </>
  )
}
