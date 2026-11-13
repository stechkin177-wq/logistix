import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useCanWrite } from '../../../shared/auth/useCanWrite'
import { NO_ERRORS, serverErrors, type FormErrors } from '../../../shared/forms/serverErrors'
import { useFocusInvalid } from '../../../shared/forms/useFocusInvalid'
import { selectableValues, useHandbookValues } from '../../../shared/handbooks/useHandbook'
import { useSaveParty } from '../hooks'
import type { Carrier, Client, Party, PartyKind, PartyPayload, PartyStatus } from '../types'
import { newContactRow, type ContactRow } from './ContactsEditor'

export interface PartyFormState {
  name: string
  bin_iin: string
  type: string
  status: PartyStatus
  notes: string
  address: string
  bank: string
  iban: string
  credit_limit: string
  rating: string
  contacts: ContactRow[]
}

export function initialPartyState(kind: PartyKind, party: Party | null): PartyFormState {
  return {
    name: party?.name ?? '',
    bin_iin: party?.bin_iin ?? '',
    type: party?.type != null ? String(party.type) : '',
    status: party?.status ?? 'active',
    notes: party?.notes ?? '',
    address: party?.address ?? '',
    bank: party?.bank ?? '',
    iban: party?.iban ?? '',
    credit_limit: kind === 'clients' && party ? (party as Client).credit_limit : '0',
    rating: kind === 'carriers' && party ? ((party as Carrier).rating ?? '') : '',
    contacts: (party?.contacts ?? []).map((c) => newContactRow({ ...c })),
  }
}

const MONEY_RE = /^\d{1,12}(\.\d{1,2})?$/
const RATING_RE = /^[0-5](\.\d)?$/
export const PARTY_FIELD_PATHS = /^(name|bin_iin|type|status|notes|address|bank|iban|credit_limit|rating|contacts(\.\d+\.(name|position|phone|email))?)$/

export function validateParty(kind: PartyKind, form: PartyFormState, t: (key: string) => string): Record<string, string> {
  const errors: Record<string, string> = {}
  if (!form.name.trim()) errors.name = t('errors.requiredField')
  if (kind === 'clients' && !MONEY_RE.test(form.credit_limit.trim())) errors.credit_limit = t('errors.invalidNumber')
  if (kind === 'carriers' && form.rating.trim() && !RATING_RE.test(form.rating.trim())) errors.rating = t('parties.ratingRange')
  form.contacts.forEach((c, i) => {
    if (!c.name.trim()) errors[`contacts.${i}.name`] = t('errors.requiredField')
  })
  return errors
}

/** includeBank=false: карточка стороны, где счета ведутся отдельно (единый источник), bank/iban не отправляются. */
export function partyPayload(kind: PartyKind, form: PartyFormState, includeBank = true): PartyPayload {
  return {
    name: form.name.trim(),
    bin_iin: form.bin_iin.trim(),
    type: form.type ? Number(form.type) : null,
    status: form.status,
    notes: form.notes,
    address: form.address.trim(),
    ...(includeBank ? { bank: form.bank.trim(), iban: form.iban.trim() } : {}),
    contacts: form.contacts.map((c) => ({
      ...(c.id !== undefined ? { id: c.id } : {}),
      name: c.name.trim(),
      position: c.position,
      phone: c.phone,
      email: c.email,
    })),
    ...(kind === 'clients' ? { credit_limit: form.credit_limit.trim() } : { rating: form.rating.trim() || null }),
  }
}

export interface PartyFormApi {
  form: PartyFormState
  set: <K extends keyof PartyFormState>(key: K, value: PartyFormState[K]) => void
  errors: FormErrors
  submit: () => void
  isPending: boolean
  editing: boolean
  canSave: boolean
  typeOptions: { value: string; label: string }[]
}

/**
 * Состояние и сохранение формы клиента/перевозчика: общее для окна создания и страницы карточки.
 * onSaved вызывается после успешного сохранения.
 */
export function usePartyForm(
  kind: PartyKind,
  party: Party | null,
  onSaved?: (saved: Party) => void,
  options: { includeBank?: boolean } = {},
) {
  const { t } = useTranslation()
  const [form, setForm] = useState(() => initialPartyState(kind, party))
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS)
  const formRef = useRef<HTMLFormElement>(null)
  const save = useSaveParty(kind)
  const editing = party !== null
  const canSave = useCanWrite(`${kind}.${editing ? 'update' : 'create'}`)
  const types = useHandbookValues(kind === 'clients' ? 'client_type' : 'carrier_type')
  const typeOptions = selectableValues(types.all, party?.type).map((v) => ({ value: String(v.id), label: v.name }))
  useFocusInvalid(formRef, errors)

  const set = <K extends keyof PartyFormState>(key: K, value: PartyFormState[K]) => {
    setForm((f) => ({ ...f, [key]: value }))
  }

  const submit = () => {
    const local = validateParty(kind, form, t)
    if (Object.keys(local).length > 0) {
      setErrors({ fields: local, banner: undefined })
      return
    }
    setErrors(NO_ERRORS)
    save.mutate(
      { id: party?.id ?? null, body: partyPayload(kind, form, options.includeBank ?? true) },
      {
        onSuccess: (saved) => { onSaved?.(saved) },
        onError: (error) => { setErrors(serverErrors(error, t, (path) => PARTY_FIELD_PATHS.test(path))) },
      },
    )
  }

  // formRef отдельно от api: объект с ref нельзя читать при отрисовке (правило react-hooks/refs)
  const api: PartyFormApi = { form, set, errors, submit, isPending: save.isPending, editing, canSave, typeOptions }
  return { api, formRef }
}
