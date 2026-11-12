import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { useSession } from '../../shared/auth/useSession'
import { Badge } from '../../shared/ui/Badge'
import { Button } from '../../shared/ui/Button'
import { Checkbox } from '../../shared/ui/Checkbox'
import { Drawer } from '../../shared/ui/Drawer'
import { EmptyState } from '../../shared/ui/EmptyState'
import { FormBanner } from '../../shared/ui/FormBanner'
import { Tabs } from '../../shared/ui/Tabs'
import { TextField } from '../../shared/ui/TextField'
import { WriteButton } from '../../shared/ui/WriteButton'
import { useArchiveDocumentType, useDocumentTypes, useSaveDocumentType } from './hooks'
import { STD_FIELDS, type DocSubject, type DocumentType, type ExtraField, type StdField } from './types'
import { PageHeader } from '../../shared/ui/PageHeader'
import { FileCog } from '../../shared/ui/icons'

const ACCESS: Record<DocSubject, { module: string; section: string }> = {
  tractor: { module: 'fleet', section: 'fleet' },
  trailer: { module: 'fleet', section: 'fleet' },
  driver: { module: 'drivers', section: 'drivers' },
}

function parseDays(raw: string): number[] {
  return raw.split(/[\s,;]+/).filter(Boolean).map(Number)
}

function TypeDrawer({ subject, type, onClose }: { subject: DocSubject; type: DocumentType | null; onClose: () => void }) {
  const { t } = useTranslation()
  const save = useSaveDocumentType()
  const [name, setName] = useState(type?.name ?? '')
  const [fields, setFields] = useState<StdField[]>(type?.fields ?? [...STD_FIELDS])
  const [required, setRequired] = useState<StdField[]>(type?.required ?? [])
  const [extra, setExtra] = useState<ExtraField[]>(type?.extra ?? [])
  const [remind, setRemind] = useState(type?.remind ?? false)
  const [days, setDays] = useState((type?.remind_days ?? [30, 7]).join(', '))
  const [active, setActive] = useState(type?.is_active ?? true)
  const [error, setError] = useState<string>()

  const toggle = (list: StdField[], f: StdField, on: boolean) => (on ? [...list, f] : list.filter((x) => x !== f))
  const submit = () => {
    setError(undefined)
    if (!name.trim()) { setError(`${t('doctypes.name')}: ${t('errors.requiredField')}`); return }
    const remindDays = parseDays(days)
    if (remind && (remindDays.length === 0 || remindDays.some((d) => !Number.isInteger(d) || d < 1))) { setError(t('doctypes.daysInvalid')); return }
    const body = {
      name: name.trim(), fields, required, remind,
      extra: extra.map((e, i) => ({ ...e, key: e.key || `f${String(i + 1)}` })),
      ...(remind ? { remind_days: remindDays } : {}),
      is_active: active,
      ...(type ? {} : { subject }),
    }
    save.mutate({ id: type?.id ?? null, body }, { onSuccess: onClose, onError: (e) => { setError(errorMessage(e, t)) } })
  }

  return (
    <Drawer
      open
      title={type ? type.name : t('doctypes.new')}
      onClose={onClose}
      busy={save.isPending}
      footer={
        <>
          <Button onClick={onClose} disabled={save.isPending}>{t('common.cancel')}</Button>
          <Button variant="primary" onClick={submit} disabled={save.isPending}>{t('common.save')}</Button>
        </>
      }
    >
      <div className="space-y-3">
        <FormBanner message={error} />
        <TextField label={t('doctypes.name')} required value={name} onChange={(e) => { setName(e.target.value) }} />
        <Checkbox label={t('doctypes.active')} checked={active} onChange={(e) => { setActive(e.target.checked) }} />
        <h3 className="text-sm font-semibold">{t('doctypes.fieldsTitle')}</h3>
        <p className="text-xs text-muted">{t('doctypes.fieldsHint')}</p>
        <ul className="space-y-1">
          {STD_FIELDS.map((f) => (
            <li key={f} className="flex items-center gap-4">
              <Checkbox label={t(`doctypes.fields.${f}`)} checked={fields.includes(f)} onChange={(e) => {
                setFields((s) => toggle(s, f, e.target.checked))
                if (!e.target.checked) setRequired((s) => s.filter((x) => x !== f))
              }} />
              {fields.includes(f) ? <Checkbox label={t('doctypes.requiredField')} checked={required.includes(f)} onChange={(e) => { setRequired((s) => toggle(s, f, e.target.checked)) }} /> : null}
            </li>
          ))}
        </ul>
        <h3 className="text-sm font-semibold">{t('doctypes.extraTitle')}</h3>
        <ul className="space-y-2">
          {extra.map((e, i) => (
            <li key={e.key || String(i)} className="flex items-end gap-2">
              <TextField label={t('doctypes.extraLabel')} value={e.label} onChange={(ev) => { setExtra((s) => s.map((x, j) => (j === i ? { ...x, label: ev.target.value } : x))) }} />
              <Checkbox label={t('doctypes.requiredField')} checked={e.required} onChange={(ev) => { setExtra((s) => s.map((x, j) => (j === i ? { ...x, required: ev.target.checked } : x))) }} />
              <Button variant="ghost" onClick={() => { setExtra((s) => s.filter((_, j) => j !== i)) }}>{t('common.delete')}</Button>
            </li>
          ))}
        </ul>
        {extra.length < 10 ? <Button onClick={() => { setExtra((s) => [...s, { key: `f${String(Date.now() % 100000)}`, label: '', required: false }]) }}>{t('doctypes.addExtra')}</Button> : null}
        <h3 className="text-sm font-semibold">{t('doctypes.remindTitle')}</h3>
        <Checkbox label={t('doctypes.remind')} checked={remind} onChange={(e) => { setRemind(e.target.checked) }} />
        {remind ? <TextField label={t('doctypes.remindDays')} hint={t('doctypes.remindDaysHint')} value={days} onChange={(e) => { setDays(e.target.value) }} /> : null}
      </div>
    </Drawer>
  )
}

function SubjectTab({ subject }: { subject: DocSubject }) {
  const { t } = useTranslation()
  const [showArchived, setShowArchived] = useState(false)
  const list = useDocumentTypes(subject, showArchived)
  const archive = useArchiveDocumentType()
  const save = useSaveDocumentType()
  const [editor, setEditor] = useState<{ type: DocumentType | null; nonce: number } | null>(null)
  const [error, setError] = useState<string>()
  const permission = `${ACCESS[subject].section}.update`
  const fail = (e: unknown) => { setError(errorMessage(e, t)) }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Checkbox label={t('doctypes.showArchived')} checked={showArchived} onChange={(e) => { setShowArchived(e.target.checked) }} />
        <WriteButton permission={permission} variant="primary" onClick={() => { setEditor({ type: null, nonce: Date.now() }) }}>{t('doctypes.new')}</WriteButton>
      </div>
      <FormBanner message={error} />
      {list.data && list.data.length === 0 ? <EmptyState title={t('doctypes.empty')} /> : null}
      <ul className="divide-y divide-slate-200 text-sm">
        {list.data?.map((row) => (
          <li key={row.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <div className="space-x-2">
              <span className="font-medium">{row.name}</span>
              {row.archived_at ? <Badge tone="warning">{t('doctypes.archived')}</Badge> : !row.is_active ? <Badge>{t('doctypes.disabled')}</Badge> : null}
              {row.remind ? <Badge tone="info">{t('doctypes.remindBadge', { days: row.remind_days.join(', ') })}</Badge> : null}
            </div>
            <div className="flex gap-1">
              {row.archived_at ? (
                <WriteButton permission={permission} onClick={() => { setError(undefined); archive.mutate({ id: row.id, archive: false }, { onError: fail }) }}>{t('doctypes.unarchive')}</WriteButton>
              ) : (
                <>
                  <WriteButton permission={permission} onClick={() => { setEditor({ type: row, nonce: Date.now() }) }}>{t('common.edit')}</WriteButton>
                  <WriteButton permission={permission} onClick={() => { setError(undefined); save.mutate({ id: row.id, body: { is_active: !row.is_active } }, { onError: fail }) }}>
                    {row.is_active ? t('doctypes.disable') : t('doctypes.enable')}
                  </WriteButton>
                  <WriteButton permission={permission} onClick={() => { setError(undefined); archive.mutate({ id: row.id, archive: true }, { onError: fail }) }}>{t('doctypes.archive')}</WriteButton>
                </>
              )}
            </div>
          </li>
        ))}
      </ul>
      {editor ? <TypeDrawer key={editor.nonce} subject={subject} type={editor.type} onClose={() => { setEditor(null) }} /> : null}
    </div>
  )
}

/** Настройки: типы документов техники и водителей (отдельно для тягачей, полуприцепов и водителей). */
export function DocumentTypesPage() {
  const { t } = useTranslation()
  const { session, hasPermission } = useSession()
  const subjects = (Object.keys(ACCESS) as DocSubject[]).filter(
    (s) => session?.modules.includes(ACCESS[s].module) && hasPermission(`${ACCESS[s].section}.view`),
  )
  const [tab, setTab] = useState<DocSubject | undefined>()
  const active = tab && subjects.includes(tab) ? tab : subjects[0]
  if (!active) return <EmptyState title={t('doctypes.noAccess')} />
  return (
    <div className="space-y-3">
      <PageHeader icon={FileCog} title={t('doctypes.title')} />
      <p className="text-sm text-muted">{t('doctypes.intro')}</p>
      <Tabs label={t('doctypes.title')} tabs={subjects.map((s) => ({ key: s, label: t(`doctypes.subjects.${s}`) }))} active={active} onChange={(k) => { setTab(k as DocSubject) }} />
      <SubjectTab key={active} subject={active} />
    </div>
  )
}
