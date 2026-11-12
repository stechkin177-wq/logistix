import { useTranslation } from 'react-i18next'
import { Button } from '../../../shared/ui/Button'
import { Drawer } from '../../../shared/ui/Drawer'
import { FormBanner } from '../../../shared/ui/FormBanner'
import { WriteButton } from '../../../shared/ui/WriteButton'
import type { Party, PartyKind } from '../types'
import { ContactsEditor } from './ContactsEditor'
import { PartyMainFields, PartyRequisitesFields } from './PartyFields'
import { usePartyForm } from './usePartyForm'

interface Props {
  kind: PartyKind
  /** null - создание; иначе правка (правка клиента и перевозчика теперь на странице карточки). */
  party: Party | null
  open: boolean
  onClose: () => void
  /** После успешного создания (например, перейти в карточку). */
  onSaved?: (saved: Party) => void
}

/** Окно создания клиента/перевозчика: основные поля, реквизиты и контакты одним списком. */
export function PartyDrawer({ kind, party, open, onClose, onSaved }: Props) {
  const { t } = useTranslation()
  // форма пересоздаётся при каждом открытии (key задаёт родитель), поэтому состояние инициализируется один раз
  const { api, formRef } = usePartyForm(kind, party, (saved) => { onClose(); onSaved?.(saved) })
  const permission = `${kind}.${api.editing ? 'update' : 'create'}`
  const title = api.editing ? t(`parties.${kind}.edit`) : t(`parties.${kind}.new`)
  return (
    <Drawer
      open={open}
      title={title}
      onClose={onClose}
      busy={api.isPending}
      footer={
        <>
          <Button onClick={onClose} disabled={api.isPending}>
            {t('common.cancel')}
          </Button>
          <WriteButton permission={permission} variant="primary" onClick={api.submit} disabled={api.isPending}>
            {api.isPending ? t('common.saving') : t('common.save')}
          </WriteButton>
        </>
      }
    >
      <form
        ref={formRef}
        noValidate
        onSubmit={(event) => {
          event.preventDefault()
          if (api.canSave) api.submit()
        }}
        className="space-y-4"
      >
        <FormBanner message={api.errors.banner} />
        <PartyMainFields kind={kind} api={api} />
        <PartyRequisitesFields api={api} />
        <ContactsEditor disabled={!api.canSave} rows={api.form.contacts} errors={api.errors.fields} onChange={(rows) => { api.set('contacts', rows) }} />
      </form>
    </Drawer>
  )
}
