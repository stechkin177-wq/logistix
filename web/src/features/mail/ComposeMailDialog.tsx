import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { Select } from '../../shared/ui/Select'
import { TextArea, TextField } from '../../shared/ui/TextField'
import { renderMailTemplate } from './api'
import { useMailTemplates, useSendMail } from './hooks'
import type { MailContext } from './types'

const splitAddresses = (raw: string) => raw.split(/[,;\s]+/).map((s) => s.trim()).filter(Boolean)

/** Новое письмо: получатели, тема, текст, шаблон с подстановкой; отправка или черновик. */
export function ComposeMailDialog({ context, onClose }: { context?: MailContext; onClose: () => void }) {
  const { t } = useTranslation()
  const send = useSendMail()
  const templates = useMailTemplates()
  const [to, setTo] = useState(context?.to ?? '')
  const [cc, setCc] = useState('')
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [templateError, setTemplateError] = useState<string | null>(null)
  const submit = (asDraft: boolean) => {
    send.mutate(
      { to: splitAddresses(to), cc: splitAddresses(cc), subject: subject.trim(), body, order: context?.order, trip: context?.trip, client: context?.client, send: !asDraft },
      { onSuccess: onClose },
    )
  }
  const applyTemplate = (id: string) => {
    if (!id) return
    setTemplateError(null)
    renderMailTemplate(Number(id), { order: context?.order, trip: context?.trip, client: context?.client })
      .then((r) => { setSubject(r.subject); setBody(r.body) })
      .catch((e: unknown) => { setTemplateError(errorMessage(e, t)) })
  }
  const busy = send.isPending
  const ready = splitAddresses(to).length > 0 && subject.trim().length > 0
  return (
    <Dialog
      open
      title={t('mail.composeTitle')}
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>{t('common.cancel')}</Button>
          <Button onClick={() => { submit(true) }} disabled={busy || !ready}>{t('mail.saveDraft')}</Button>
          <Button variant="primary" onClick={() => { submit(false) }} disabled={busy || !ready}>{busy ? t('mail.sending') : t('mail.send')}</Button>
        </>
      }
    >
      <form className="space-y-3" noValidate onSubmit={(e) => { e.preventDefault(); if (ready) submit(false) }}>
        {send.isError ? <Banner kind="error">{errorMessage(send.error, t)}</Banner> : null}
        {templateError ? <Banner kind="error">{templateError}</Banner> : null}
        <TextField label={t('mail.to')} required value={to} placeholder="name@company.kz" onChange={(e) => { setTo(e.target.value) }} hint={t('mail.addressesHint')} />
        <TextField label={t('mail.cc')} value={cc} onChange={(e) => { setCc(e.target.value) }} />
        {templates.data && templates.data.length > 0 ? (
          <Select label={t('mail.template')} value="" placeholder={t('mail.pickTemplate')} options={templates.data.map((x) => ({ value: String(x.id), label: x.name }))} onChange={applyTemplate} />
        ) : null}
        <TextField label={t('mail.subject')} required maxLength={200} value={subject} onChange={(e) => { setSubject(e.target.value) }} />
        <TextArea label={t('mail.body')} rows={8} value={body} onChange={(e) => { setBody(e.target.value) }} />
      </form>
    </Dialog>
  )
}
