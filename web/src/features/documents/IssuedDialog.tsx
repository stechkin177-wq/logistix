import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { downloadIssued, saveDownloaded } from './api'
import { useCapabilities } from './hooks'
import type { FileFormat, IssuedDocument } from './types'

/** Кнопки «DOCX» и «PDF» (PDF скрыта, если сервер не умеет конвертировать). Скачивание - авторизованным запросом. */
export function DownloadButtons({ doc, onError, long = false }: { doc: IssuedDocument; onError: (message: string) => void; long?: boolean }) {
  const { t } = useTranslation()
  const caps = useCapabilities()
  const [busy, setBusy] = useState<FileFormat | null>(null)
  const run = async (format: FileFormat) => {
    onError('')
    setBusy(format)
    try {
      await saveDownloaded(downloadIssued(doc.id, format), `${doc.number}.${format}`)
    } catch (error) {
      onError(errorMessage(error, t))
    } finally {
      setBusy(null)
    }
  }
  const formats: FileFormat[] = caps.data?.pdf_available ? ['docx', 'pdf'] : ['docx']
  return (
    <>
      {formats.map((format) => (
        <Button
          key={format}
          disabled={busy !== null}
          aria-label={t(`documents.issued.download_${format}`, { number: doc.number })}
          onClick={() => { void run(format) }}
        >
          {long ? t(`documents.issued.long_${format}`) : format.toUpperCase()}
        </Button>
      ))}
    </>
  )
}

/** «Документ <номер> выдан» со скачиванием. error - уже переведённая ошибка выдачи (если документ не создан). */
export function IssuedDialog({ doc, error, onClose }: { doc: IssuedDocument | null; error?: string; onClose: () => void }) {
  const { t } = useTranslation()
  const [downloadError, setDownloadError] = useState('')
  const message = error || downloadError
  return (
    <Dialog
      open
      title={doc ? t('documents.issued.issuedTitle', { number: doc.number }) : t('documents.issued.failedTitle')}
      onClose={onClose}
      footer={
        <>
          {doc ? <DownloadButtons doc={doc} onError={setDownloadError} long /> : null}
          <Button data-autofocus onClick={onClose}>{t('common.close')}</Button>
        </>
      }
    >
      <div className="space-y-2">
        {doc ? <p className="text-sm">{t('documents.issued.issuedHint')}</p> : null}
        {message ? <Banner kind="error">{message}</Banner> : null}
      </div>
    </Dialog>
  )
}
