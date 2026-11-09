import { useMutation } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../../shared/api/client'
import { setTokens } from '../../shared/auth/tokens'
import { NO_ERRORS, serverErrors, type FormErrors } from '../../shared/forms/serverErrors'
import { useFocusInvalid } from '../../shared/forms/useFocusInvalid'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { FormBanner } from '../../shared/ui/FormBanner'
import { TextField } from '../../shared/ui/TextField'
import { pushToast } from '../../shared/ui/toast'

const FIELDS = ['old_password', 'new_password']

/**
 * Смена собственного пароля. Пароли живут только в состоянии этого компонента (он размонтируется
 * при закрытии) и уходят в одном запросе; в URL, localStorage и кэш запросов не попадают.
 */
export function ChangePasswordDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation()
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS)
  const formRef = useRef<HTMLFormElement>(null)
  useFocusInvalid(formRef, errors)

  const save = useMutation({
    mutationFn: () => api.post<{ access: string; refresh: string }>('/auth/password/', { old_password: oldPassword, new_password: newPassword }),
    onSuccess: (tokens) => {
      // сервер отозвал прежние токены: продолжаем на новых (контекст сохраняется)
      setTokens(tokens)
      pushToast('info', t('account.passwordChanged'))
      onClose()
    },
    onError: (error) => {
      setErrors(serverErrors(error, t, (p) => FIELDS.includes(p)))
    },
  })

  const submit = () => {
    const local: Record<string, string> = {}
    if (!oldPassword) local.old_password = t('errors.requiredField')
    if (!newPassword) local.new_password = t('errors.requiredField')
    else if (newPassword === oldPassword) local.new_password = t('account.sameAsOld')
    if (newPassword && confirm !== newPassword) local.confirm = t('account.mismatch')
    if (Object.keys(local).length > 0) {
      setErrors({ fields: local, banner: undefined })
      return
    }
    setErrors(NO_ERRORS)
    save.mutate()
  }

  const f = errors.fields
  return (
    <Dialog
      open
      title={t('account.changePassword')}
      onClose={onClose}
      busy={save.isPending}
      footer={
        <>
          <Button onClick={onClose} disabled={save.isPending}>{t('common.cancel')}</Button>
          <Button variant="primary" onClick={submit} disabled={save.isPending}>
            {save.isPending ? t('common.saving') : t('common.save')}
          </Button>
        </>
      }
    >
      <form ref={formRef} noValidate className="space-y-3" onSubmit={(e) => { e.preventDefault(); submit() }}>
        <FormBanner message={errors.banner} />
        <TextField label={t('account.oldPassword')} type="password" required value={oldPassword} error={f.old_password} autoComplete="current-password" onChange={(e) => { setOldPassword(e.target.value) }} />
        <TextField label={t('account.newPassword')} type="password" required value={newPassword} error={f.new_password} hint={t('account.newPasswordHint')} autoComplete="new-password" onChange={(e) => { setNewPassword(e.target.value) }} />
        <TextField label={t('account.confirmPassword')} type="password" required value={confirm} error={f.confirm} autoComplete="new-password" onChange={(e) => { setConfirm(e.target.value) }} />
      </form>
    </Dialog>
  )
}
