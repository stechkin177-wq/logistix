import { useTranslation } from 'react-i18next'
import { useSession } from '../auth/useSession'
import { formatDate, formatDateTime } from './datetime'
import { formatMoney } from './money'

/** Форматирование для экранов: пояс - из сессии компании, язык - из i18n. */
export function useFormat() {
  const { i18n } = useTranslation()
  const { session } = useSession()
  const tz = session?.company.timezone
  const lang = i18n.language
  return {
    tz,
    dateTime: (value: string | null | undefined) => formatDateTime(value, tz, lang),
    date: (value: string | null | undefined) => formatDate(value, tz, lang),
    money: (value: string | null | undefined, currency?: string) =>
      formatMoney(value, { currency, decimalSeparator: ',' }),
  }
}
