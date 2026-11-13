import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { useFormat } from '../../shared/format/useFormat'
import { Badge } from '../../shared/ui/Badge'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { Card, CardHeader } from '../../shared/ui/Card'
import { ConfirmDialog } from '../../shared/ui/ConfirmDialog'
import { DateInput } from '../../shared/ui/DateInput'
import { Dialog } from '../../shared/ui/Dialog'
import { EmptyState } from '../../shared/ui/EmptyState'
import { FileText, Pencil, Trash2 } from '../../shared/ui/icons'
import { Select } from '../../shared/ui/Select'
import { Spinner } from '../../shared/ui/Spinner'
import { TextArea, TextField } from '../../shared/ui/TextField'
import { WriteButton } from '../../shared/ui/WriteButton'
import { useContracts, useDeleteContract, useSaveContract } from './hooks'
import type { Contract, ContractKind, PartyOwner } from './types'

const KINDS: ContractKind[] = ['main', 'supplement', 'other']

interface FormState {
  kind: ContractKind
  number: string
  date: string
  valid_until: string
  title: string
  comment: string
}

const empty = (): FormState => ({ kind: 'main', number: '', date: '', valid_until: '', title: '', comment: '' })

function ContractDialog({ owner, contract, onClose }: { owner: PartyOwner; contract: Contract | null; onClose: () => void }) {
  const { t } = useTranslation()
  const save = useSaveContract()
  const [form, setForm] = useState<FormState>(
    contract
      ? { kind: contract.kind, number: contract.number, date: contract.date, valid_until: contract.valid_until ?? '', title: contract.title, comment: contract.comment }
      : empty(),
  )
  const [local, setLocal] = useState<Record<string, string>>({})
  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => { setForm((f) => ({ ...f, [key]: value })) }
  const permission = owner.kind === 'client' ? 'clients.update' : 'carriers.update'

  const submit = () => {
    const errors: Record<string, string> = {}
    if (!form.number.trim()) errors.number = t('errors.requiredField')
    if (!form.date) errors.date = t('errors.requiredField')
    if (form.valid_until && form.date && form.valid_until < form.date) errors.valid_until = t('contracts.untilBeforeDate')
    setLocal(errors)
    if (Object.keys(errors).length > 0) return
    save.mutate(
      {
        id: contract?.id ?? null,
        body: {
          ...(contract ? {} : { [owner.kind]: owner.id }),
          kind: form.kind,
          number: form.number.trim(),
          date: form.date,
          valid_until: form.valid_until || null,
          title: form.title.trim(),
          comment: form.comment,
        },
      },
      { onSuccess: onClose },
    )
  }
  const serverField = (name: string): string | undefined => {
    const fields = (save.error as { fields?: Record<string, string[] | string> } | null)?.fields
    const value = fields?.[name]
    return Array.isArray(value) ? value[0] : value
  }
  return (
    <Dialog
      open
      title={contract ? t('contracts.edit') : t('contracts.new')}
      onClose={onClose}
      busy={save.isPending}
      footer={
        <>
          <Button onClick={onClose} disabled={save.isPending}>{t('common.cancel')}</Button>
          <WriteButton permission={permission} variant="primary" onClick={submit} disabled={save.isPending}>
            {save.isPending ? t('common.saving') : t('common.save')}
          </WriteButton>
        </>
      }
    >
      <form noValidate className="space-y-3" onSubmit={(e) => { e.preventDefault(); submit() }}>
        {save.isError && !serverField('number') && !serverField('valid_until') ? <Banner kind="error">{errorMessage(save.error, t)}</Banner> : null}
        <Select label={t('contracts.kind')} value={form.kind} options={KINDS.map((k) => ({ value: k, label: t(`contracts.kinds.${k}`) }))} onChange={(v) => { set('kind', KINDS.find((k) => k === v) ?? 'main') }} />
        <TextField label={t('contracts.number')} required value={form.number} error={local.number ?? serverField('number')} onChange={(e) => { set('number', e.target.value) }} />
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <DateInput label={t('contracts.date')} required value={form.date} error={local.date} onChange={(v) => { set('date', v) }} />
          <DateInput label={t('contracts.validUntil')} value={form.valid_until} error={local.valid_until ?? serverField('valid_until')} onChange={(v) => { set('valid_until', v) }} />
        </div>
        <TextField label={t('contracts.title')} value={form.title} onChange={(e) => { set('title', e.target.value) }} />
        <TextArea label={t('common.comment')} value={form.comment} onChange={(e) => { set('comment', e.target.value) }} />
      </form>
    </Dialog>
  )
}

/** Договоры стороны: реестр с добавлением, правкой и удалением (удалить договор, выбранный в заказах/рейсах, нельзя). */
export function ContractsPanel({ owner }: { owner: PartyOwner }) {
  const { t } = useTranslation()
  const { date } = useFormat()
  const list = useContracts(owner)
  const remove = useDeleteContract()
  const [editor, setEditor] = useState<{ contract: Contract | null; nonce: number } | null>(null)
  const [toDelete, setToDelete] = useState<Contract | null>(null)
  const permission = owner.kind === 'client' ? 'clients.update' : 'carriers.update'
  const rows = list.data?.results ?? []

  return (
    <Card>
      <CardHeader
        title={t('contracts.title')}
        hint={t('contracts.hint')}
        actions={<WriteButton permission={permission} variant="primary" onClick={() => { setEditor({ contract: null, nonce: Date.now() }) }}>{t('contracts.add')}</WriteButton>}
      />
      {list.isPending ? <div className="p-4"><Spinner label={t('common.loading')} /></div> : null}
      {list.isError ? <div className="p-4"><Banner kind="error">{errorMessage(list.error, t)}</Banner></div> : null}
      {list.data && rows.length === 0 ? <EmptyState icon={FileText} title={t('contracts.empty')} hint={t('contracts.emptyHint')} /> : null}
      {rows.length > 0 ? (
        <ul className="divide-y divide-line text-sm">
          {rows.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-3">
              <span className="min-w-0">
                <span className="font-medium">{c.number}</span>
                <span className="ml-2 text-muted">
                  {t(`contracts.kinds.${c.kind}`)} · {date(c.date)}
                  {c.valid_until ? ` — ${date(c.valid_until)}` : ` · ${t('contracts.perpetual')}`}
                </span>
                {c.title ? <span className="block text-xs text-muted">{c.title}</span> : null}
              </span>
              <span className="flex items-center gap-2">
                {c.is_expired ? <Badge tone="warning">{t('contracts.expired')}</Badge> : null}
                {c.source === 'imported' ? <Badge>{t('contracts.imported')}</Badge> : null}
                <WriteButton permission={permission} variant="ghost" icon={Pencil} aria-label={t('contracts.editNamed', { number: c.number })} onClick={() => { setEditor({ contract: c, nonce: Date.now() }) }} />
                <WriteButton permission={permission} variant="ghost" icon={Trash2} aria-label={t('contracts.deleteNamed', { number: c.number })} onClick={() => { setToDelete(c) }} />
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {editor ? <ContractDialog key={editor.nonce} owner={owner} contract={editor.contract} onClose={() => { setEditor(null) }} /> : null}
      <ConfirmDialog
        open={toDelete !== null}
        danger
        title={t('contracts.deleteTitle')}
        message={t('contracts.deleteMessage', { number: toDelete?.number ?? '' })}
        confirmLabel={t('common.delete')}
        busy={remove.isPending}
        error={remove.isError ? errorMessage(remove.error, t) : undefined}
        onConfirm={() => { if (toDelete) remove.mutate(toDelete.id, { onSuccess: () => { setToDelete(null) } }) }}
        onCancel={() => { setToDelete(null); remove.reset() }}
      />
    </Card>
  )
}
