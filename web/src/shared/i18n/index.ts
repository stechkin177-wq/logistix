import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import kk from './kk.json'
import ru from './ru.json'

export const LANGUAGES = ['ru', 'kk'] as const
export type Language = (typeof LANGUAGES)[number]

const STORAGE_KEY = 'logistix.lang'

export function isLanguage(value: unknown): value is Language {
  return typeof value === 'string' && (LANGUAGES as readonly string[]).includes(value)
}

function storedLanguage(): Language | null {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY)
    return isLanguage(value) ? value : null
  } catch {
    return null
  }
}

function browserLanguage(): Language {
  const nav = typeof navigator === 'undefined' ? '' : navigator.language
  return nav.toLowerCase().startsWith('kk') ? 'kk' : 'ru'
}

/** Явный выбор пользователя запоминается и главнее языка компании. */
export function setLanguage(lng: Language): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, lng)
  } catch {
    // хранилище недоступно - язык действует до перезагрузки
  }
  void i18n.changeLanguage(lng)
}

/** Язык компании из сессии, если пользователь сам язык не выбирал. */
export function applyCompanyLanguage(language: string): void {
  if (storedLanguage() === null && isLanguage(language)) void i18n.changeLanguage(language)
}

void i18n.use(initReactI18next).init({
  resources: { ru: { translation: ru }, kk: { translation: kk } },
  lng: storedLanguage() ?? browserLanguage(),
  fallbackLng: 'ru',
  supportedLngs: [...LANGUAGES],
  interpolation: { escapeValue: false }, // React экранирует сам
  initAsync: false,
})

function syncHtmlLang(lng: string): void {
  document.documentElement.lang = lng
}
i18n.on('languageChanged', syncHtmlLang)
syncHtmlLang(i18n.language)

export default i18n
