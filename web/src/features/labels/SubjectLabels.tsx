import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { useCanWrite } from '../../shared/auth/useCanWrite'
import { useSession } from '../../shared/auth/useSession'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { Checkbox } from '../../shared/ui/Checkbox'
import { Dialog } from '../../shared/ui/Dialog'
import { Plus, Tag } from '../../shared/ui/icons'
import { Select } from '../../shared/ui/Select'
import { TextField } from '../../shared/ui/TextField'
import { useCreateLabel, useLabels, useSetSubjectLabels } from './hooks'
import { LabelChip, LabelChips } from './LabelChip'
import { LABEL_COLORS, type LabelRef, type LabelSubject } from './types'

const SECTION: Record<LabelSubject, string> = { order: 'orders', trip: 'trips', client: 'clients', carrier: 'carriers' }

function PickerDialog({ kind, id, current, onClose }: { kind: LabelSubject; id: number; current: LabelRef[]; onClose: () => void }) {
  const { t } = useTranslation()
  const { hasPermission } = useSession()
  const all = useLabels()
  const save = useSetSubjectLabels(kind, id)
  const create = useCreateLabel()
  const [selected, setSelected] = useState<Set<number>>(new Set(current.map((l) => l.id)))
  const [name, setName] = useState('')
  const [color, setColor] = useState('blue')
  const canManage = hasPermission('labels.manage')
  const toggle = (labelId: number, on: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (on) next.add(labelId)
      else next.delete(labelId)
      return next
    })
  }
  const addNew = () => {
    if (!name.trim()) return
    create.mutate({ name: name.trim(), color }, { onSuccess: (label) => { toggle(label.id, true); setName('') } })
  }
  return (
    <Dialog
      open
      title={t('labels.pickerTitle')}
      onClose={onClose}
      busy={save.isPending}
      footer={
        <>
          <Button onClick={onClose} disabled={save.isPending}>{t('common.cancel')}</Button>
          <Button variant="primary" disabled={save.isPending} onClick={() => { save.mutate([...selected], { onSuccess: onClose }) }}>
            {save.isPending ? t('common.saving') : t('common.save')}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {save.isError ? <Banner kind="error">{errorMessage(save.error, t)}</Banner> : null}
        {all.data && all.data.length === 0 ? <p className="text-sm text-muted">{t('labels.noneYet')}</p> : null}
        <ul className="space-y-1">
          {(all.data ?? []).map((l) => (
            <li key={l.id} className="flex items-center gap-2">
              <Checkbox label={<LabelChip label={l} />} checked={selected.has(l.id)} onChange={(e) => { toggle(l.id, e.target.checked) }} />
            </li>
          ))}
        </ul>
        {canManage ? (
          <form className="grid grid-cols-[1fr_auto_auto] items-end gap-2 border-t border-line pt-3" onSubmit={(e) => { e.preventDefault(); addNew() }}>
            <TextField label={t('labels.newName')} value={name} maxLength={64} error={create.isError ? errorMessage(create.error, t) : undefined} onChange={(e) => { setName(e.target.value) }} />
            <Select label={t('labels.color')} value={color} options={LABEL_COLORS.map((c) => ({ value: c, label: t(`labels.colors.${c}`) }))} onChange={setColor} />
            <Button type="submit" icon={Plus} disabled={!name.trim() || create.isPending}>{t('labels.create')}</Button>
          </form>
        ) : null}
      </div>
    </Dialog>
  )
}

/**
 * Метки объекта: чипы и кнопка выбора. Менять набор может тот, кто правит сам объект
 * (<раздел>.update); создавать новые метки в окне - тот, у кого есть labels.manage.
 */
export function SubjectLabels({ kind, id, labels }: { kind: LabelSubject; id: number; labels: LabelRef[] | undefined }) {
  const { t } = useTranslation()
  const canEdit = useCanWrite(`${SECTION[kind]}.update`)
  const [open, setOpen] = useState(false)
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <LabelChips labels={labels} />
      {canEdit ? (
        <Button variant="ghost" icon={Tag} className="h-7 px-2 text-xs" aria-label={labels && labels.length > 0 ? t('labels.editAria') : t('labels.addAria')} onClick={() => { setOpen(true) }}>
          {labels && labels.length > 0 ? t('labels.edit') : t('labels.add')}
        </Button>
      ) : null}
      {open ? <PickerDialog key={`${kind}-${String(id)}`} kind={kind} id={id} current={labels ?? []} onClose={() => { setOpen(false) }} /> : null}
    </span>
  )
}
