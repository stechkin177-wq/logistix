import { useTranslation } from 'react-i18next'
import { PageHeader } from '../../../shared/ui/PageHeader'
import { Palette } from '../../../shared/ui/icons'
import { BrandingBlock } from './BrandingBlock'

/** Оформление: название, цвет, тема и логотип компании (отдельная вкладка профиля). */
export function BrandingPage() {
  const { t } = useTranslation()
  return (
    <div className="space-y-3">
      <PageHeader icon={Palette} title={t('nav.branding')} hint="branding" />
      <BrandingBlock />
    </div>
  )
}
