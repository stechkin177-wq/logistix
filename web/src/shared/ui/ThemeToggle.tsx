import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { setThemeOverride } from '../branding/applyBranding'
import { Moon, Sun } from './icons'

const isDark = () => document.documentElement.classList.contains('dark')

/** Кнопка-переключатель светлой/тёмной темы: значок показывает, на какую тему перейдём. */
export function ThemeToggle({ className = '' }: { className?: string }) {
  const { t } = useTranslation()
  const [dark, setDark] = useState(isDark)
  useEffect(() => {
    const observer = new MutationObserver(() => { setDark(isDark()) })
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    return () => { observer.disconnect() }
  }, [])
  const Icon = dark ? Sun : Moon
  const label = dark ? t('common.themeLight') : t('common.themeDark')
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={() => { setThemeOverride(dark ? 'light' : 'dark') }}
      className={`inline-flex size-9 items-center justify-center rounded-control border border-line bg-surface text-muted shadow-card transition-colors hover:text-ink ${className}`}
    >
      <Icon className="size-4" aria-hidden="true" />
    </button>
  )
}
