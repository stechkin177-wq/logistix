import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { Card, CardHeader } from '../../shared/ui/Card'
import { ConfirmDialog } from '../../shared/ui/ConfirmDialog'
import { Dialog } from '../../shared/ui/Dialog'
import { Pencil, Trash2, Mail } from '../../shared/ui/icons'
import { PageHeader } from '../../shared/ui/PageHeader'
import { Select } from '../../shared/ui/Select'
import { Spinner } from '../../shared/ui/Spinner'
import { TextArea, TextField } from '../../shared/ui/TextField'
import { WriteButton } from '../../shared/ui/WriteButton'
import {
  useCreateMailTemplate, useDeleteMailTemplate, useMailAccount, useMailTemplates, useSaveMailAccount, useTestMailAccount,
  useUpdateMailTemplate,
} from './hooks'
import type { MailAccount, MailAccountForm, MailSecurity, MailTemplate } from './types'

const SECURITY: MailSecurity[] = ['starttls', 'ssl', 'none']
const DEFAULT_PORT: Record<MailSecurity, number> = { starttls: 587, ssl: 465, none: 25 }

function AccountForm({ account }: { account: MailAccount }) {
  const { t } = useTranslation()
  const save = useSaveMailAccount()
  const test = useTestMailAccount()
  const [form, setForm] = useState<MailAccountForm>({
    host: account.host ?? '', port: account.port ?? 587, security: account.security ?? 'starttls', username: account.username ?? '',
    password: '', from_email: account.from_email ?? '', from_name: account.from_name ?? '', is_active: account.is_active ?? true,
  })
  const set = <K extends keyof MailAccountForm>(key: K, value: MailAccountForm[K]) => { setForm((f) => ({ ...f, [key]: value })) }
  return (
    <Card>
      <CardHeader title={t('mail.accountTitle')} />
      <form className="grid gap-3 p-4 sm:grid-cols-2" noValidate onSubmit={(e) => { e.preventDefault(); save.mutate(form) }}>
        <TextField label={t('mail.host')} required value={form.host} onChange={(e) => { set('host', e.target.value) }} placeholder="smtp.company.kz" />
        <Select label={t('mail.security')} value={form.security} options={SECURITY.map((s) => ({ value: s, label: t(`mail.securityKinds.${s}`) }))} onChange={(v) => { const s = SECURITY.find((x) => x === v) ?? 'starttls'; setForm((f) => ({ ...f, security: s, port: DEFAULT_PORT[s] })) }} />
        <TextField label={t('mail.port')} type="number" value={form.port} onChange={(e) => { set('port', Number(e.target.value)) }} hint={t('mail.portHint')} />
        <TextField label={t('mail.username')} value={form.username} autoComplete="off" onChange={(e) => { set('username', e.target.value) }} />
        <TextField
          label={t('mail.password')}
          type="password"
          autoComplete="new-password"
          value={form.password}
          onChange={(e) => { set('password', e.target.value) }}
          hint={account.has_password ? t('mail.passwordKept') : t('mail.passwordHint')}
        />
        <TextField label={t('mail.fromEmail')} type="email" required value={form.from_email} onChange={(e) => { set('from_email', e.target.value) }} />
        <TextField label={t('mail.fromName')} value={form.from_name} onChange={(e) => { set('from_name', e.target.value) }} />
        <label className="flex items-center gap-2 self-end pb-2 text-sm">
          <input type="checkbox" checked={form.is_active} onChange={(e) => { set('is_active', e.target.checked) }} />
          {t('mail.active')}
        </label>
        <div className="space-y-2 sm:col-span-2">
          {save.isError ? <Banner kind="error">{errorMessage(save.error, t)}</Banner> : null}
          {save.isSuccess ? <Banner kind="info">{t('mail.saved')}</Banner> : null}
          {test.isError ? <Banner kind="error">{errorMessage(test.error, t)}</Banner> : null}
          {test.data ? (
            <Banner kind={test.data.state === 'sent' ? 'info' : 'error'}>
              {test.data.state === 'sent' ? t('mail.testSent', { to: test.data.to }) : t('mail.testFailed', { error: test.data.error })}
            </Banner>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <WriteButton type="submit" permission="mail.manage_account" variant="primary" disabled={save.isPending || !form.host.trim() || !form.from_email.trim()}>
              {save.isPending ? t('common.saving') : t('common.save')}
            </WriteButton>
            <WriteButton permission="mail.manage_account" disabled={!account.configured || test.isPending} onClick={() => { test.mutate() }} title={account.configured ? undefined : t('mail.saveFirst')}>
              {test.isPending ? t('mail.sending') : t('mail.sendTest')}
            </WriteButton>
          </div>
        </div>
      </form>
    </Card>
  )
}

function TemplateDialog({ template, onClose }: { template: MailTemplate | null; onClose: () => void }) {
  const { t } = useTranslation()
  const create = useCreateMailTemplate()
  const update = useUpdateMailTemplate()
  const [name, setName] = useState(template?.name ?? '')
  const [subject, setSubject] = useState(template?.subject ?? '')
  const [body, setBody] = useState(template?.body ?? '')
  const busy = create.isPending || update.isPending
  const error = template ? update.error : create.error
  const submit = () => {
    if (!name.trim()) return
    const payload = { name: name.trim(), subject, body }
    if (template) update.mutate({ id: template.id, body: payload }, { onSuccess: onClose })
    else create.mutate(payload, { onSuccess: onClose })
  }
  return (
    <Dialog
      open
      title={template ? t('mail.templateEdit') : t('mail.templateNew')}
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>{t('common.cancel')}</Button>
          <Button variant="primary" onClick={submit} disabled={busy || !name.trim()}>{busy ? t('common.saving') : t('common.save')}</Button>
        </>
      }
    >
      <form className="space-y-3" noValidate onSubmit={(e) => { e.preventDefault(); submit() }}>
        {error ? <Banner kind="error">{errorMessage(error, t)}</Banner> : null}
        <TextField label={t('mail.templateName')} required value={name} maxLength={120} onChange={(e) => { setName(e.target.value) }} />
        <TextField label={t('mail.subject')} value={subject} maxLength={200} onChange={(e) => { setSubject(e.target.value) }} />
        <TextArea label={t('mail.body')} rows={8} value={body} onChange={(e) => { setBody(e.target.value) }} hint={t('mail.placeholdersHint')} />
      </form>
    </Dialog>
  )
}

function Templates() {
  const { t } = useTranslation()
  const list = useMailTemplates()
  const remove = useDeleteMailTemplate()
  const [editor, setEditor] = useState<{ template: MailTemplate | null; nonce: number } | null>(null)
  const [toDelete, setToDelete] = useState<MailTemplate | null>(null)
  return (
    <Card>
      <CardHeader title={t('mail.templatesTitle')} actions={<WriteButton permission="mail.manage_account" onClick={() => { setEditor({ template: null, nonce: Date.now() }) }}>{t('mail.templateNew')}</WriteButton>} />
      {list.isPending ? <div className="p-4"><Spinner label={t('common.loading')} /></div> : null}
      {list.isError ? <div className="p-4"><Banner kind="error">{errorMessage(list.error, t)}</Banner></div> : null}
      {list.data && list.data.length === 0 ? <p className="p-4 text-sm text-muted">{t('mail.templatesEmpty')}</p> : null}
      {list.data && list.data.length > 0 ? (
        <ul className="divide-y divide-line text-sm">
          {list.data.map((x) => (
            <li key={x.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
              <span><span className="font-medium">{x.name}</span><span className="block text-xs text-muted">{x.subject}</span></span>
              <span className="flex items-center gap-1">
                <WriteButton permission="mail.manage_account" variant="ghost" icon={Pencil} aria-label={t('mail.templateEditNamed', { name: x.name })} onClick={() => { setEditor({ template: x, nonce: Date.now() }) }} />
                <WriteButton permission="mail.manage_account" variant="ghost" icon={Trash2} aria-label={t('mail.templateDeleteNamed', { name: x.name })} onClick={() => { setToDelete(x) }} />
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {editor ? <TemplateDialog key={editor.nonce} template={editor.template} onClose={() => { setEditor(null) }} /> : null}
      <ConfirmDialog
        open={toDelete !== null}
        danger
        title={t('mail.templateDeleteTitle')}
        message={t('mail.templateDeleteMessage', { name: toDelete?.name ?? '' })}
        confirmLabel={t('common.delete')}
        busy={remove.isPending}
        error={remove.isError ? errorMessage(remove.error, t) : undefined}
        onConfirm={() => { if (toDelete) remove.mutate(toDelete.id, { onSuccess: () => { setToDelete(null) } }) }}
        onCancel={() => { setToDelete(null); remove.reset() }}
      />
    </Card>
  )
}

/** Настройки почты: SMTP-ящик компании (пароль только на запись) и шаблоны писем. */
export function MailSettingsPage() {
  const { t } = useTranslation()
  const account = useMailAccount()
  return (
    <div className="space-y-4">
      <PageHeader icon={Mail} title={t('nav.mailSettings')} subtitle={t('mail.settingsIntro')} />
      {account.isPending ? <Spinner label={t('common.loading')} /> : null}
      {account.isError ? <Banner kind="error">{errorMessage(account.error, t)}</Banner> : null}
      {account.data ? <AccountForm key={account.dataUpdatedAt} account={account.data} /> : null}
      <Templates />
    </div>
  )
}
