import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '../../shared/ui/Button'
import { Mail } from '../../shared/ui/icons'
import { ComposeMailDialog } from './ComposeMailDialog'
import { useMailStatus } from './hooks'
import type { MailContext } from './types'

/** «Написать письмо» в карточке заказа, рейса или клиента; скрыта без права mail.send, отключена без ящика. */
export function ComposeMailButton({ context }: { context: MailContext }) {
  const { t } = useTranslation()
  const { allowed, configured } = useMailStatus()
  const [open, setOpen] = useState(false)
  if (!allowed) return null
  return (
    <>
      <Button icon={Mail} disabled={!configured} title={configured ? undefined : t('mail.notConfigured')} onClick={() => { setOpen(true) }}>
        {t('mail.write')}
      </Button>
      {open ? <ComposeMailDialog context={context} onClose={() => { setOpen(false) }} /> : null}
    </>
  )
}
