import { useFormat } from '../format/useFormat'

/** Денежная строка API с группировкой разрядов; null/мусор - "—". Число не парсится. */
export function Money({ value, currency }: { value: string | null | undefined; currency?: string }) {
  const { money } = useFormat()
  return <span className="whitespace-nowrap tabular-nums">{money(value, currency)}</span>
}
