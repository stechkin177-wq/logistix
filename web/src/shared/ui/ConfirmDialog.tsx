import { useTranslation } from 'react-i18next'
import { Banner } from './Banner'
import { Button } from './Button'
import { Dialog } from './Dialog'

interface Props {
  open: boolean
  title: string
  message: string
  confirmLabel?: string
  danger?: boolean
  busy?: boolean
  /** Уже переведённый текст ошибки операции. */
  error?: string
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmDialog({ open, title, message, confirmLabel, danger, busy, error, onConfirm, onCancel }: Props) {
  const { t } = useTranslation()
  return (
    <Dialog
      open={open}
      title={title}
      role="alertdialog"
      busy={busy}
      onClose={onCancel}
      footer={
        <>
          <Button data-autofocus onClick={onCancel} disabled={busy}>
            {t('common.cancel')}
          </Button>
          <Button variant={danger ? 'danger' : 'primary'} onClick={onConfirm} disabled={busy}>
            {confirmLabel ?? t('dialog.confirm')}
          </Button>
        </>
      }
    >
      <div className="space-y-2">
        <p className="text-sm">{message}</p>
        {error ? <Banner kind="error">{error}</Banner> : null}
      </div>
    </Dialog>
  )
}
