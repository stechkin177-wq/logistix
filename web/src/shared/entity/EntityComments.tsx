import { useState, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Banner } from '../ui/Banner'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { DateTime } from '../ui/DateTime'
import { EmptyState } from '../ui/EmptyState'
import { MessageSquare, Send } from '../ui/icons'
import { Spinner } from '../ui/Spinner'
import { TextArea } from '../ui/TextField'

export interface EntityComment {
  id: number | string
  author: string
  created_at: string
  text: string
}

interface Props {
  comments: EntityComment[]
  /** Отправка нового комментария; без неё поле ввода не показывается (режим только чтения). */
  onAdd?: (text: string) => Promise<unknown>
  loading?: boolean
  /** Уже переведённый текст ошибки. */
  error?: string
  /** Отправка идёт: поле и кнопка заблокированы. */
  busy?: boolean
}

/**
 * Сквозной блок комментариев записи (заказ, рейс, клиент...). Только вид и ввод: откуда приходят
 * комментарии и куда уходят, решает вызывающая сторона через comments/onAdd. Ctrl+Enter отправляет.
 */
export function EntityComments({ comments, onAdd, loading, error, busy }: Props) {
  const { t } = useTranslation()
  const [text, setText] = useState('')
  const trimmed = text.trim()

  const send = async () => {
    if (!onAdd || !trimmed || busy) return
    await onAdd(trimmed)
    setText('')
  }
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault()
      void send()
    }
  }

  return (
    <div className="space-y-3">
      {error ? <Banner kind="error">{error}</Banner> : null}
      {loading ? <Spinner label={t('common.loading')} /> : null}
      {!loading && comments.length === 0 ? <Card><EmptyState icon={MessageSquare} title={t('entity.commentsEmpty')} /></Card> : null}
      {comments.length > 0 ? (
        <Card>
          <ul aria-label={t('entity.comments')} className="divide-y divide-line">
            {comments.map((c) => (
              <li key={c.id} className="px-4 py-3">
                <p className="text-xs text-muted">
                  <span className="font-medium text-ink">{c.author}</span> · <DateTime value={c.created_at} />
                </p>
                <p className="mt-1 whitespace-pre-wrap text-sm">{c.text}</p>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
      {onAdd ? (
        <form
          className="space-y-2"
          onSubmit={(event) => {
            event.preventDefault()
            void send()
          }}
        >
          <TextArea
            label={t('entity.commentLabel')}
            placeholder={t('entity.commentPlaceholder')}
            value={text}
            disabled={busy}
            onKeyDown={onKeyDown}
            onChange={(event) => { setText(event.target.value) }}
          />
          <div className="flex justify-end">
            <Button variant="primary" type="submit" icon={Send} disabled={!trimmed || busy}>
              {t('entity.commentSend')}
            </Button>
          </div>
        </form>
      ) : null}
    </div>
  )
}
