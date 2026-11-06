import { useFormat } from '../format/useFormat'

/** Момент в часовом поясе компании. dateOnly - только дата. */
export function DateTime({ value, dateOnly }: { value: string | null | undefined; dateOnly?: boolean }) {
  const { dateTime, date } = useFormat()
  return <span className="whitespace-nowrap tabular-nums">{dateOnly ? date(value) : dateTime(value)}</span>
}
