import { useRef, useState } from 'react'
import { errorMessage } from '../../shared/api/errors'
import { useSession } from '../../shared/auth/useSession'
import type { ButtonProps } from '../../shared/ui/Button'
import { WriteButton } from '../../shared/ui/WriteButton'
import { useTranslation } from 'react-i18next'
import { useIssueDocument } from './hooks'
import { IssuedDialog } from './IssuedDialog'
import type { DocumentKind, IssuedDocument, IssueSource } from './types'

/** Модуль-владелец вида документа: акт и счёт на оплату принадлежат finance, остальные виды - logistics. */
const KIND_MODULE: Record<DocumentKind, string> = {
  contract: 'logistics',
  order_request: 'logistics',
  carrier_order: 'logistics',
  cmr: 'logistics',
  letter: 'logistics',
  act: 'finance',
  invoice_print: 'finance',
}

interface Props extends Pick<ButtonProps, 'variant'> {
  kind: DocumentKind
  /** Ровно один источник: клиент, заказ, рейс или счёт. */
  source: IssueSource
  /** Текст кнопки (название документа). */
  label: string
}

/** Кнопка «выдать документ»: POST issued/, затем диалог со скачиванием. Скрыта без модуля documents или модуля-владельца вида (logistics/finance), отключена без documents.create. */
export function IssueDocumentButton({ kind, source, label, variant }: Props) {
  const { t } = useTranslation()
  const { hasModule } = useSession()
  const issue = useIssueDocument()
  const busy = useRef(false)
  const [result, setResult] = useState<{ doc: IssuedDocument | null; error?: string } | null>(null)

  if (!hasModule('documents') || !hasModule(KIND_MODULE[kind])) return null

  const run = () => {
    if (busy.current) return // второй клик, пока идёт запрос, документ не создаёт
    busy.current = true
    issue.mutate(
      { kind, ...source },
      {
        onSuccess: (doc) => { setResult({ doc }) },
        onError: (error) => { setResult({ doc: null, error: errorMessage(error, t) }) },
        onSettled: () => { busy.current = false },
      },
    )
  }

  return (
    <>
      <WriteButton permission="documents.create" variant={variant} disabled={issue.isPending} onClick={run}>
        {label}
      </WriteButton>
      {result ? <IssuedDialog doc={result.doc} error={result.error} onClose={() => { setResult(null); issue.reset() }} /> : null}
    </>
  )
}
