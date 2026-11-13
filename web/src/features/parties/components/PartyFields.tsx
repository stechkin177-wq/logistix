import { useTranslation } from 'react-i18next'
import { Select } from '../../../shared/ui/Select'
import { TextArea, TextField } from '../../../shared/ui/TextField'
import type { PartyKind } from '../types'
import type { PartyFormApi } from './usePartyForm'

type Api = Pick<PartyFormApi, 'form' | 'set' | 'errors' | 'typeOptions'>

/** Основные поля: название, БИН/ИИН, тип, статус, кредитный лимит или рейтинг, примечание. */
export function PartyMainFields({ kind, api }: { kind: PartyKind; api: Api }) {
  const { t } = useTranslation()
  const { form, set, errors, typeOptions } = api
  const f = errors.fields
  return (
    <div className="space-y-3">
      <TextField label={t('parties.name')} required value={form.name} error={f.name} onChange={(e) => { set('name', e.target.value) }} />
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
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
    </div>
  )
}

/** Только адрес (банковские счета в карточке ведутся отдельным блоком). */
export function PartyAddressField({ api }: { api: Api }) {
  const { t } = useTranslation()
  return <TextField label={t('parties.address')} value={api.form.address} error={api.errors.fields.address} onChange={(e) => { api.set('address', e.target.value) }} />
}

/** Адрес и банковские реквизиты (одна пара банк/IBAN; расширение до нескольких счетов - в техническом предложении). */
export function PartyRequisitesFields({ api }: { api: Api }) {
  const { t } = useTranslation()
  const { form, set, errors } = api
  const f = errors.fields
  return (
    <div className="space-y-3">
      <TextField label={t('parties.address')} value={form.address} error={f.address} onChange={(e) => { set('address', e.target.value) }} />
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <TextField label={t('parties.bank')} value={form.bank} error={f.bank} onChange={(e) => { set('bank', e.target.value) }} />
        <TextField label={t('parties.iban')} value={form.iban} error={f.iban} hint={t('parties.ibanHint')} onChange={(e) => { set('iban', e.target.value) }} />
      </div>
    </div>
  )
}
