import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { Card } from '../../shared/ui/Card'
import { ConfirmDialog } from '../../shared/ui/ConfirmDialog'
import { Dialog } from '../../shared/ui/Dialog'
import { EmptyState } from '../../shared/ui/EmptyState'
import { Pencil, Tag, Trash2 } from '../../shared/ui/icons'
import { PageHeader } from '../../shared/ui/PageHeader'
import { Select } from '../../shared/ui/Select'
import { Spinner } from '../../shared/ui/Spinner'
import { TextField } from '../../shared/ui/TextField'
import { WriteButton } from '../../shared/ui/WriteButton'
import { useCreateLabel, useDeleteLabel, useLabels, useUpdateLabel } from './hooks'
import { LabelChip } from './LabelChip'
import { LABEL_COLORS, type Label } from './types'

function LabelDialog({ label, onClose }: { label: Label | null; onClose: () => void }) {
  const { t } = useTranslation()
  const create = useCreateLabel()
  const update = useUpdateLabel()
  const [name, setName] = useState(label?.name ?? '')
  const [color, setColor] = useState(label?.color ?? 'blue')
  const busy = create.isPending || update.isPending
  const error = label ? update.error : create.error
  const submit = () => {
    if (!name.trim()) return
    if (label) update.mutate({ id: label.id, body: { name: name.trim(), color } }, { onSuccess: onClose })
    else create.mutate({ name: name.trim(), color }, { onSuccess: onClose })
  }
  return (
    <Dialog
      open
      title={label ? t('labels.editTitle') : t('labels.newTitle')}
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
        <TextField label={t('labels.name')} required value={name} maxLength={64} onChange={(e) => { setName(e.target.value) }} />
        <Select label={t('labels.color')} value={color} options={LABEL_COLORS.map((c) => ({ value: c, label: t(`labels.colors.${c}`) }))} onChange={setColor} />
        <p className="text-xs text-muted">{t('labels.preview')}: <LabelChip label={{ name: name.trim() || t('labels.name'), color }} /></p>
      </form>
    </Dialog>
  )
}

/** Метки компании: создание, правка, удаление (право labels.manage). */
export function LabelsPage() {
  const { t } = useTranslation()
  const list = useLabels()
  const remove = useDeleteLabel()
  const [editor, setEditor] = useState<{ label: Label | null; nonce: number } | null>(null)
  const [toDelete, setToDelete] = useState<Label | null>(null)
  const rows = list.data ?? []
  return (
    <div className="space-y-4">
      <PageHeader
        icon={Tag}
        title={t('nav.labels')}
        subtitle={t('labels.intro')}
        actions={<WriteButton permission="labels.manage" variant="primary" onClick={() => { setEditor({ label: null, nonce: Date.now() }) }}>{t('labels.create')}</WriteButton>}
      />
      <Card>
        {list.isPending ? <div className="p-4"><Spinner label={t('common.loading')} /></div> : null}
        {list.isError ? <div className="p-4"><Banner kind="error">{errorMessage(list.error, t)}</Banner></div> : null}
        {list.data && rows.length === 0 ? <EmptyState icon={Tag} title={t('labels.empty')} hint={t('labels.emptyHint')} /> : null}
        {rows.length > 0 ? (
          <ul className="divide-y divide-line text-sm">
            {rows.map((l) => (
              <li key={l.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                <span className="flex items-center gap-3">
                  <LabelChip label={l} />
                  <span className="text-xs text-muted">{t('labels.usage', { count: l.usage_count })}</span>
                </span>
                <span className="flex items-center gap-1">
                  <WriteButton permission="labels.manage" variant="ghost" icon={Pencil} aria-label={t('labels.editNamed', { name: l.name })} onClick={() => { setEditor({ label: l, nonce: Date.now() }) }} />
                  <WriteButton permission="labels.manage" variant="ghost" icon={Trash2} aria-label={t('labels.deleteNamed', { name: l.name })} onClick={() => { setToDelete(l) }} />
                </span>
              </li>
            ))}
          </ul>
        ) : null}
      </Card>
      {editor ? <LabelDialog key={editor.nonce} label={editor.label} onClose={() => { setEditor(null) }} /> : null}
      <ConfirmDialog
        open={toDelete !== null}
        danger
        title={t('labels.deleteTitle')}
        message={t('labels.deleteMessage', { name: toDelete?.name ?? '', count: toDelete?.usage_count ?? 0 })}
        confirmLabel={t('common.delete')}
        busy={remove.isPending}
        error={remove.isError ? errorMessage(remove.error, t) : undefined}
        onConfirm={() => { if (toDelete) remove.mutate(toDelete.id, { onSuccess: () => { setToDelete(null) } }) }}
        onCancel={() => { setToDelete(null); remove.reset() }}
      />
    </div>
  )
}
