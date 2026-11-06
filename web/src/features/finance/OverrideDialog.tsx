import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { TextField } from '../../shared/ui/TextField'

interface Props {
  canOverride: boolean
  busy: boolean
  /** Уже переведённый текст ошибки повторной попытки. */
  error?: string
  onConfirm: (reason: string) => void
  onCancel: () => void
}

/** Превышен кредитный лимит клиента: выставить сверх лимита можно с правом и обязательной причиной. */
export function OverrideDialog({ canOverride, busy, error, onConfirm, onCancel }: Props) {
  const { t } = useTranslation()
  const [reason, setReason] = useState('')
  const [local, setLocal] = useState<string | undefined>()
  const confirm = () => {
    if (!reason.trim()) {
      setLocal(t('finance.invoices.reasonRequired'))
      return
    }
    setLocal(undefined)
    onConfirm(reason.trim())
  }
  return (
    <Dialog
      open
      title={t('finance.invoices.overrideTitle')}
      onClose={onCancel}
      busy={busy}
      footer={
        <>
          <Button onClick={onCancel} disabled={busy}>{t('common.cancel')}</Button>
          {canOverride ? (
            <Button variant="primary" disabled={busy} onClick={confirm}>{t('finance.invoices.overrideConfirm')}</Button>
          ) : null}
        </>
      }
    >
      <div className="space-y-3">
        {error ? <Banner kind="error">{error}</Banner> : null}
        {canOverride ? (
          <>
            <p className="text-sm">{t('finance.invoices.overrideHint')}</p>
            <TextField label={t('finance.invoices.overrideReason')} required value={reason} error={local} onChange={(e) => { setReason(e.target.value) }} />
          </>
        ) : (
          <p className="text-sm">{t('finance.invoices.overrideNoRight')}</p>
        )}
      </div>
    </Dialog>
  )
}
