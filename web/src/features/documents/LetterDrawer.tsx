import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { NO_ERRORS, serverErrors, type FormErrors } from '../../shared/forms/serverErrors'
import { useFocusInvalid } from '../../shared/forms/useFocusInvalid'
import { Button } from '../../shared/ui/Button'
import { Drawer } from '../../shared/ui/Drawer'
import { FormBanner } from '../../shared/ui/FormBanner'
import { TextArea, TextField } from '../../shared/ui/TextField'
import { WriteButton } from '../../shared/ui/WriteButton'
import { useIssueDocument } from './hooks'
import type { IssuedDocument } from './types'

export const LETTER_LIMITS = { recipient: 255, subject: 255, body: 20000 } as const
type Field = keyof typeof LETTER_LIMITS
const FIELDS = Object.keys(LETTER_LIMITS) as Field[]

/** Письмо на бланке: адресат, тема и текст; после выдачи вызывает onIssued с созданным документом. */
export function LetterDrawer({ onClose, onIssued }: { onClose: () => void; onIssued: (doc: IssuedDocument) => void }) {
  const { t } = useTranslation()
  const [form, setForm] = useState<Record<Field, string>>({ recipient: '', subject: '', body: '' })
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS)
  const issue = useIssueDocument()
  const ref = useRef<HTMLFormElement>(null)
  useFocusInvalid(ref, errors)

  const submit = () => {
    const local: Record<string, string> = {}
    for (const field of FIELDS) {
      const value = form[field].trim()
      if (!value) local[field] = t('errors.requiredField')
      else if (value.length > LETTER_LIMITS[field]) local[field] = t('documents.letter.tooLong', { max: LETTER_LIMITS[field] })
    }
    if (Object.keys(local).length > 0) {
      setErrors({ fields: local, banner: undefined })
      return
    }
    setErrors(NO_ERRORS)
    issue.mutate(
      { kind: 'letter', letter: { recipient: form.recipient.trim(), subject: form.subject.trim(), body: form.body.trim() } },
      {
        onSuccess: onIssued,
        onError: (error) => { setErrors(serverErrors(error, t, (p) => FIELDS.some((f) => p === f || p === `letter.${f}`))) },
      },
    )
  }
  const f = errors.fields
  const set = (field: Field, value: string) => { setForm((s) => ({ ...s, [field]: value })) }
  return (
    <Drawer
      open
      title={t('documents.letter.title')}
      onClose={onClose}
      busy={issue.isPending}
      footer={
        <>
          <Button onClick={onClose} disabled={issue.isPending}>{t('common.cancel')}</Button>
          <WriteButton permission="documents.create" variant="primary" disabled={issue.isPending} onClick={submit}>
            {issue.isPending ? t('documents.letter.issuing') : t('documents.letter.issue')}
          </WriteButton>
        </>
      }
    >
      <form ref={ref} noValidate className="space-y-3" onSubmit={(e) => { e.preventDefault(); submit() }}>
        <FormBanner message={errors.banner} />
        <TextField label={t('documents.letter.recipient')} required value={form.recipient} error={f.recipient} onChange={(e) => { set('recipient', e.target.value) }} />
        <TextField label={t('documents.letter.subject')} required value={form.subject} error={f.subject} onChange={(e) => { set('subject', e.target.value) }} />
        <TextArea
          label={t('documents.letter.body')}
          required
          rows={12}
          value={form.body}
          error={f.body}
          hint={t('documents.letter.bodyHint', { length: form.body.length, max: LETTER_LIMITS.body })}
          onChange={(e) => { set('body', e.target.value) }}
        />
      </form>
    </Drawer>
  )
}
