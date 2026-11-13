import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { Badge } from '../../shared/ui/Badge'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { Card, CardHeader } from '../../shared/ui/Card'
import { Checkbox } from '../../shared/ui/Checkbox'
import { ConfirmDialog } from '../../shared/ui/ConfirmDialog'
import { Dialog } from '../../shared/ui/Dialog'
import { EmptyState } from '../../shared/ui/EmptyState'
import { Landmark, Pencil, Trash2 } from '../../shared/ui/icons'
import { Spinner } from '../../shared/ui/Spinner'
import { TextField } from '../../shared/ui/TextField'
import { WriteButton } from '../../shared/ui/WriteButton'
import { useAccounts, useDeleteAccount, useSaveAccount } from './hooks'
import type { BankAccount, PartyOwner } from './types'

interface FormState { bank: string; bic: string; iban: string; kbe: string; currency: string; note: string; is_default: boolean }

function AccountDialog({ owner, account, onClose }: { owner: PartyOwner; account: BankAccount | null; onClose: () => void }) {
  const { t } = useTranslation()
  const save = useSaveAccount(owner)
  const [form, setForm] = useState<FormState>({
    bank: account?.bank ?? '', bic: account?.bic ?? '', iban: account?.iban ?? '', kbe: account?.kbe ?? '',
    currency: account?.currency ?? '', note: account?.note ?? '', is_default: account?.is_default ?? false,
  })
  const [local, setLocal] = useState('')
  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => { setForm((f) => ({ ...f, [key]: value })) }
  const permission = owner.kind === 'client' ? 'clients.update' : 'carriers.update'
  const fieldError = (name: string): string | undefined => {
    const fields = (save.error as { fields?: Record<string, string[] | string> } | null)?.fields
    const value = fields?.[name]
    return Array.isArray(value) ? value[0] : value
  }

  const submit = () => {
    if (!form.bank.trim() && !form.iban.trim()) {
      setLocal(t('accounts.bankOrIban'))
      return
    }
    setLocal('')
    save.mutate(
      {
        id: account?.id ?? null,
        body: {
          ...(account ? {} : { [owner.kind]: owner.id }),
          bank: form.bank.trim(), bic: form.bic.trim(), iban: form.iban, kbe: form.kbe.trim(), currency: form.currency, note: form.note.trim(),
          ...(form.is_default ? { is_default: true } : {}),
        },
      },
      { onSuccess: onClose },
    )
  }
  return (
    <Dialog
      open
      title={account ? t('accounts.edit') : t('accounts.new')}
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
        {local ? <Banner kind="error">{local}</Banner> : null}
        {save.isError && !fieldError('iban') && !fieldError('currency') ? <Banner kind="error">{errorMessage(save.error, t)}</Banner> : null}
        <TextField label={t('parties.bank')} value={form.bank} onChange={(e) => { set('bank', e.target.value) }} />
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <TextField label={t('parties.iban')} value={form.iban} error={fieldError('iban')} hint={t('parties.ibanHint')} onChange={(e) => { set('iban', e.target.value) }} />
          <TextField label={t('accounts.bic')} value={form.bic} maxLength={16} onChange={(e) => { set('bic', e.target.value) }} />
          <TextField label={t('accounts.kbe')} value={form.kbe} maxLength={4} onChange={(e) => { set('kbe', e.target.value) }} />
          <TextField label={t('accounts.currency')} value={form.currency} maxLength={3} placeholder="KZT" error={fieldError('currency')} onChange={(e) => { set('currency', e.target.value) }} />
        </div>
        <TextField label={t('accounts.note')} value={form.note} onChange={(e) => { set('note', e.target.value) }} />
        <Checkbox label={t('accounts.makeDefault')} checked={form.is_default} disabled={account?.is_default === true} onChange={(e) => { set('is_default', e.target.checked) }} />
      </form>
    </Dialog>
  )
}

/** Банковские счета стороны (единый источник реквизитов): список, добавление, правка, счёт по умолчанию. */
export function BankAccountsPanel({ owner }: { owner: PartyOwner }) {
  const { t } = useTranslation()
  const list = useAccounts(owner)
  const remove = useDeleteAccount(owner)
  const [editor, setEditor] = useState<{ account: BankAccount | null; nonce: number } | null>(null)
  const [toDelete, setToDelete] = useState<BankAccount | null>(null)
  const permission = owner.kind === 'client' ? 'clients.update' : 'carriers.update'
  const rows = list.data ?? []

  return (
    <Card>
      <CardHeader
        title={t('accounts.title')}
        hint={t('accounts.hint')}
        actions={<WriteButton permission={permission} variant="primary" onClick={() => { setEditor({ account: null, nonce: Date.now() }) }}>{t('accounts.add')}</WriteButton>}
      />
      {list.isPending ? <div className="p-4"><Spinner label={t('common.loading')} /></div> : null}
      {list.isError ? <div className="p-4"><Banner kind="error">{errorMessage(list.error, t)}</Banner></div> : null}
      {list.data && rows.length === 0 ? <EmptyState icon={Landmark} title={t('accounts.empty')} hint={t('accounts.emptyHint')} /> : null}
      {rows.length > 0 ? (
        <ul className="divide-y divide-line text-sm">
          {rows.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-3">
              <span className="min-w-0">
                <span className="font-medium">{a.bank || '—'}</span>
                <span className="ml-2 tabular-nums text-muted">{a.iban}</span>
                <span className="block text-xs text-muted">
                  {[a.currency, a.bic && `${t('accounts.bic')}: ${a.bic}`, a.kbe && `${t('accounts.kbe')}: ${a.kbe}`, a.note].filter(Boolean).join(' · ')}
                </span>
              </span>
              <span className="flex items-center gap-2">
                {a.is_default ? <Badge tone="success">{t('accounts.default')}</Badge> : null}
                <WriteButton permission={permission} variant="ghost" icon={Pencil} aria-label={t('accounts.editNamed', { iban: a.iban || a.bank })} onClick={() => { setEditor({ account: a, nonce: Date.now() }) }} />
                <WriteButton permission={permission} variant="ghost" icon={Trash2} aria-label={t('accounts.deleteNamed', { iban: a.iban || a.bank })} onClick={() => { setToDelete(a) }} />
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {editor ? <AccountDialog key={editor.nonce} owner={owner} account={editor.account} onClose={() => { setEditor(null) }} /> : null}
      <ConfirmDialog
        open={toDelete !== null}
        danger
        title={t('accounts.deleteTitle')}
        message={t('accounts.deleteMessage', { iban: toDelete?.iban || toDelete?.bank || '' })}
        confirmLabel={t('common.delete')}
        busy={remove.isPending}
        error={remove.isError ? errorMessage(remove.error, t) : undefined}
        onConfirm={() => { if (toDelete) remove.mutate(toDelete.id, { onSuccess: () => { setToDelete(null) } }) }}
        onCancel={() => { setToDelete(null); remove.reset() }}
      />
    </Card>
  )
}
