import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { Spinner } from '../../shared/ui/Spinner'
import { Download, RotateCcw } from '../../shared/ui/icons'

const ZOOMS = [1, 1.5, 2, 3, 4]

/** Фото документа: увеличение, поворот, скачивание. Изображение приходит как blob (нужен токен). */
export function ImageViewer({ blob, name, className = '' }: { blob: Blob; name: string; className?: string }) {
  const { t } = useTranslation()
  const [url, setUrl] = useState<string>()
  const [zoom, setZoom] = useState(0)
  const [turn, setTurn] = useState(0)
  useEffect(() => {
    const reader = new FileReader()
    reader.onload = () => { setUrl(typeof reader.result === 'string' ? reader.result : undefined) }
    try { reader.readAsDataURL(blob) } catch { /* не картинка: останется пустое поле */ }
    return () => { reader.onload = null }
  }, [blob])
  const rotated = turn % 180 !== 0
  return (
    <div className={`flex min-h-0 flex-col gap-2 ${className}`}>
      <div className="flex flex-wrap items-center gap-2">
        <Button disabled={zoom === 0} aria-label={t('ocr.photo.zoomOut')} onClick={() => { setZoom(Math.max(0, zoom - 1)) }}>−</Button>
        <span className="min-w-12 text-center text-xs text-muted">{Math.round((ZOOMS[zoom] ?? 1) * 100)}%</span>
        <Button disabled={zoom === ZOOMS.length - 1} aria-label={t('ocr.photo.zoomIn')} onClick={() => { setZoom(Math.min(ZOOMS.length - 1, zoom + 1)) }}>+</Button>
        <Button icon={RotateCcw} aria-label={t('ocr.photo.rotate')} onClick={() => { setTurn((turn + 90) % 360) }}>{t('ocr.photo.rotate')}</Button>
        {url ? <a className="inline-flex items-center gap-1 text-sm text-brand-700 hover:underline dark:text-brand-300" href={url} download={name || 'document.jpg'}><Download className="size-4" aria-hidden="true" />{t('ocr.photo.download')}</a> : null}
      </div>
      <div className="thin-scroll min-h-0 flex-1 overflow-auto rounded-control border border-line bg-surface-2">
        {url ? (
          <img
            src={url}
            alt={name}
            data-testid="ocr-photo"
            className="block max-w-none origin-top-left"
            style={{
              width: `${String((ZOOMS[zoom] ?? 1) * 100)}%`,
              transform: turn === 0 ? undefined : `rotate(${String(turn)}deg)`,
              margin: rotated ? '25% auto' : undefined,
            }}
          />
        ) : null}
      </div>
    </div>
  )
}

/** Загрузка фото по запросу + показ в ImageViewer; без фото (срок архива) - понятное сообщение. */
export function RemoteImage({ queryKey, load, name, className }: { queryKey: unknown[]; load: () => Promise<Blob>; name: string; className?: string }) {
  const { t } = useTranslation()
  const image = useQuery({ queryKey, queryFn: load, staleTime: 5 * 60_000, retry: false })
  if (image.isPending) return <Spinner />
  if (image.isError) return <Banner kind="error">{errorMessage(image.error, t)}</Banner>
  return <ImageViewer blob={image.data} name={name} className={className} />
}

/** Окно просмотра фото документа (приложение водителя и быстрый просмотр в офисе). */
export function PhotoDialog({ title, queryKey, load, name, onClose }: { title: string; queryKey: unknown[]; load: () => Promise<Blob>; name: string; onClose: () => void }) {
  return (
    <Dialog open title={title} onClose={onClose} width="max-w-3xl">
      <div className="flex h-[70vh] flex-col"><RemoteImage queryKey={queryKey} load={load} name={name} className="flex-1" /></div>
    </Dialog>
  )
}
