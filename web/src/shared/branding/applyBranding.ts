import type { Branding, Theme } from '../api/types'
import { DEFAULT_COLOR, LIGHT_FG, SHADE_KEYS, isHexColor, readableForeground, shadeScale } from './palette'

export const DEFAULT_APP_NAME = 'Logistix'
const THEMES: readonly string[] = ['light', 'dark', 'system']
const APP_NAME_MAX = 64

export const DEFAULT_BRANDING: Branding = {
  app_name: DEFAULT_APP_NAME,
  logo_url: null,
  primary_color: DEFAULT_COLOR,
  theme: 'system',
}

/** Название только как текст: без управляющих символов, до 64 знаков; пусто -> название платформы. */
export function safeAppName(value: unknown): string {
  if (typeof value !== 'string') return DEFAULT_APP_NAME
  // eslint-disable-next-line no-control-regex
  const cleaned = value.replace(/[\u0000-\u001f\u007f]/g, '').trim().slice(0, APP_NAME_MAX)
  return cleaned || DEFAULT_APP_NAME
}

/** Логотип только как src картинки: относительный путь или http(s). Иначе null. */
export function safeLogoUrl(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const url = value
  // пробелы и управляющие символы в любом месте (браузер вырезает \t, \n - "/\t/evil" стал бы "//evil")
  // eslint-disable-next-line no-control-regex
  if (/[\u0000- \u007f]/.test(url)) return null
  if (url.startsWith('//') || url.includes('\\')) return null
  if (/^\/[^/]/.test(url) || /^https?:\/\/[^\s]+$/i.test(url)) return url
  return null
}

export function safeTheme(value: unknown): Theme {
  return typeof value === 'string' && THEMES.includes(value) ? (value as Theme) : 'system'
}

/** Приводит ответ бэкенда к безопасным значениям (мусор -> значения по умолчанию). */
export function sanitizeBranding(raw: Partial<Record<keyof Branding, unknown>>): Branding {
  return {
    app_name: safeAppName(raw.app_name),
    logo_url: safeLogoUrl(raw.logo_url),
    primary_color: isHexColor(raw.primary_color) ? raw.primary_color : DEFAULT_COLOR,
    theme: safeTheme(raw.theme),
  }
}

let stopSystemWatch: (() => void) | null = null

function setDark(on: boolean): void {
  document.documentElement.classList.toggle('dark', on)
}

function applyTheme(theme: Theme): void {
  stopSystemWatch?.()
  stopSystemWatch = null
  if (theme !== 'system') {
    setDark(theme === 'dark')
    return
  }
  if (typeof window.matchMedia !== 'function') {
    setDark(false)
    return
  }
  const query = window.matchMedia('(prefers-color-scheme: dark)')
  setDark(query.matches)
  const listener = (event: MediaQueryListEvent): void => {
    setDark(event.matches)
  }
  query.addEventListener('change', listener)
  stopSystemWatch = () => {
    query.removeEventListener('change', listener)
  }
}

/** Выставляет CSS-переменные --brand-50..950, --brand-fg, --brand-solid-hover, класс dark и заголовок страницы. */
export function applyBranding(input: Partial<Record<keyof Branding, unknown>>): void {
  const branding = sanitizeBranding(input)
  const root = document.documentElement
  const scale = shadeScale(branding.primary_color)
  for (const key of SHADE_KEYS) root.style.setProperty(`--brand-${key}`, scale[key])
  // текст на сплошном фоне бренда (кнопки, активный вид): читаемый цвет для оттенка 600;
  // при наведении светлый текст темнит фон (700), тёмный - осветляет (500), контраст не падает
  const fg = readableForeground(scale[600])
  root.style.setProperty('--brand-fg', fg)
  root.style.setProperty('--brand-solid-hover', fg === LIGHT_FG ? scale[700] : scale[500])
  applyTheme(branding.theme)
  document.title = branding.app_name
}
