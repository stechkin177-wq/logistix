import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { serverErrors, NO_ERRORS, type FormErrors } from '../../../shared/forms/serverErrors'
import { useFocusInvalid } from '../../../shared/forms/useFocusInvalid'
import { selectableValues, useHandbookValues } from '../../../shared/handbooks/useHandbook'
import { Button } from '../../../shared/ui/Button'
import { Drawer } from '../../../shared/ui/Drawer'
import { FormBanner } from '../../../shared/ui/FormBanner'
import { Select } from '../../../shared/ui/Select'
import { TextArea, TextField } from '../../../shared/ui/TextField'
import { WriteButton } from '../../../shared/ui/WriteButton'
import { useCanWrite } from '../../../shared/auth/useCanWrite'
import { IssueDocumentButton } from '../../documents/IssueDocumentButton'
import { useSaveParty } from '../hooks'
import type { Carrier, Client, Party, PartyKind, PartyPayload, PartyStatus } from '../types'
import { ContactsEditor, newContactRow, type ContactRow } from './ContactsEditor'

interface FormState {
  name: string
  bin_iin: string
  type: string
  status: PartyStatus
  notes: string
  credit_limit: string
  rating: string
  contacts: ContactRow[]
}

function initialState(kind: PartyKind, party: Party | null): FormState {
  return {
    name: party?.name ?? '',
    bin_iin: party?.bin_iin ?? '',
    type: party?.type != null ? String(party.type) : '',
    status: party?.status ?? 'active',
    notes: party?.notes ?? '',
    credit_limit: kind === 'clients' && party ? (party as Client).credit_limit : '0',
    rating: kind === 'carriers' && party ? ((party as Carrier).rating ?? '') : '',
    contacts: (party?.contacts ?? []).map((c) => newContactRow({ ...c })),
  }
}

const MONEY_RE = /^\d{1,12}(\.\d{1,2})?$/
const RATING_RE = /^[0-5](\.\d)?$/
const KNOWN = /^(name|bin_iin|type|status|notes|credit_limit|rating|contacts(\.\d+\.(name|position|phone|email))?)$/

function validate(kind: PartyKind, form: FormState, t: (key: string) => string): Record<string, string> {
  const errors: Record<string, string> = {}
  if (!form.name.trim()) errors.name = t('errors.requiredField')
  if (kind === 'clients' && !MONEY_RE.test(form.credit_limit.trim())) errors.credit_limit = t('errors.invalidNumber')
  if (kind === 'carriers' && form.rating.trim() && !RATING_RE.test(form.rating.trim())) errors.rating = t('parties.ratingRange')
  form.contacts.forEach((c, i) => {
    if (!c.name.trim()) errors[`contacts.${i}.name`] = t('errors.requiredField')
  })
  return errors
}

interface Props {
  kind: PartyKind
  /** null - создание; иначе правка. */
  party: Party | null
  open: boolean
  onClose: () => void
}

export function PartyDrawer({ kind, party, open, onClose }: Props) {
  const { t } = useTranslation()
  // форма пересоздаётся при каждом открытии (key задаёт родитель), поэтому состояние инициализируется один раз
  const [form, setForm] = useState(() => initialState(kind, party))
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS)
  const formRef = useRef<HTMLFormElement>(null)
  const save = useSaveParty(kind)
  const editing = party !== null
  const canSave = useCanWrite(`${kind}.${editing ? 'update' : 'create'}`)
  const types = useHandbookValues(kind === 'clients' ? 'client_type' : 'carrier_type')
  const typeOptions = selectableValues(types.all, party?.type).map((v) => ({ value: String(v.id), label: v.name }))
  useFocusInvalid(formRef, errors)

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((f) => ({ ...f, [key]: value }))
  }

  const submit = () => {
    const local = validate(kind, form, t)
    if (Object.keys(local).length > 0) {
      setErrors({ fields: local, banner: undefined })
      return
    }
    const body: PartyPayload = {
      name: form.name.trim(),
      bin_iin: form.bin_iin.trim(),
      type: form.type ? Number(form.type) : null,
      status: form.status,
      notes: form.notes,
      contacts: form.contacts.map((c) => ({
        ...(c.id !== undefined ? { id: c.id } : {}),
        name: c.name.trim(),
        position: c.position,
        phone: c.phone,
        email: c.email,
      })),
      ...(kind === 'clients' ? { credit_limit: form.credit_limit.trim() } : { rating: form.rating.trim() || null }),
    }
    setErrors(NO_ERRORS)
    save.mutate(
      { id: party?.id ?? null, body },
      {
        onSuccess: onClose,
        onError: (error) => {
          setErrors(serverErrors(error, t, (path) => KNOWN.test(path)))
        },
      },
    )
  }

  const f = errors.fields
  const title = editing ? t(`parties.${kind}.edit`) : t(`parties.${kind}.new`)
  return (
    <Drawer
      open={open}
      title={title}
      onClose={onClose}
      busy={save.isPending}
      footer={
        <>
          <Button onClick={onClose} disabled={save.isPending}>
            {t('common.cancel')}
          </Button>
          <WriteButton permission={`${kind}.${editing ? 'update' : 'create'}`} variant="primary" onClick={submit} disabled={save.isPending}>
            {save.isPending ? t('common.saving') : t('common.save')}
          </WriteButton>
        </>
      }
    >
      <form
        ref={formRef}
        noValidate
        onSubmit={(event) => {
          event.preventDefault()
          if (canSave) submit()
        }}
        className="space-y-3"
      >
        <FormBanner message={errors.banner} />
        <TextField label={t('parties.name')} required value={form.name} error={f.name} onChange={(e) => { set('name', e.target.value) }} />
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <TextField label={t('parties.binIin')} inputMode="numeric" value={form.bin_iin} error={f.bin_iin} hint={t('parties.binHint')} onChange={(e) => { set('bin_iin', e.target.value) }} />
          <Select label={t('parties.type')} value={form.type} placeholder={t('common.none')} options={typeOptions} error={f.type} onChange={(v) => { set('type', v) }} />
          <Select
            label={t('common.status')}
            value={form.status}
            error={f.status}
            options={[
              { value: 'active', label: t('common.active') },
              { value: 'inactive', label: t('common.inactive') },
            ]}
            onChange={(v) => { set('status', v === 'inactive' ? 'inactive' : 'active') }}
          />
          {kind === 'clients' ? (
            <TextField label={t('parties.creditLimit')} inputMode="decimal" value={form.credit_limit} error={f.credit_limit} onChange={(e) => { set('credit_limit', e.target.value) }} />
          ) : (
            <TextField label={t('parties.rating')} inputMode="decimal" value={form.rating} error={f.rating} hint={t('parties.ratingHint')} onChange={(e) => { set('rating', e.target.value) }} />
          )}
        </div>
        <TextArea label={t('parties.notes')} value={form.notes} error={f.notes} onChange={(e) => { set('notes', e.target.value) }} />
        <ContactsEditor disabled={!canSave} rows={form.contacts} errors={f} onChange={(rows) => { set('contacts', rows) }} />
        {kind === 'clients' && party ? (
          <section aria-labelledby="party-documents" className="space-y-1">
            <h3 id="party-documents" className="text-xs font-medium">{t('documents.title')}</h3>
            <IssueDocumentButton kind="contract" source={{ client: party.id }} label={t('documents.kind.contract')} />
          </section>
        ) : null}
      </form>
    </Drawer>
  )
}
