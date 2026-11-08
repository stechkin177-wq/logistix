import { useQueryClient, useMutation } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../../../shared/api/client'
import { useCanWrite } from '../../../shared/auth/useCanWrite'
import { useSession } from '../../../shared/auth/useSession'
import { NO_ERRORS, serverErrors, type FormErrors } from '../../../shared/forms/serverErrors'
import { useFocusInvalid } from '../../../shared/forms/useFocusInvalid'
import { Banner } from '../../../shared/ui/Banner'
import { Button } from '../../../shared/ui/Button'
import { Checkbox } from '../../../shared/ui/Checkbox'
import { Drawer } from '../../../shared/ui/Drawer'
import { FormBanner } from '../../../shared/ui/FormBanner'
import { TextField } from '../../../shared/ui/TextField'
import { WriteButton } from '../../../shared/ui/WriteButton'
import { ACTIONS, ALL_CODES, EXTRA_CODES, MODULE_CODES, SECTIONS } from './catalog'

export interface Role {
  id: number
  name: string
  is_system: boolean
  permissions: string[]
}

/** Матрица прав: разделы x действия. Права, которых нет у вас самих, отключены (сервер проверяет это же правило). */
export function RoleDrawer({ role, onClose }: { role: Role | null; onClose: () => void }) {
  const { t } = useTranslation()
  const { hasPermission } = useSession()
  const qc = useQueryClient()
  const readOnlyRole = role?.is_system === true
  const editing = role !== null
  const canSave = useCanWrite(editing ? 'roles.update' : 'roles.create')
  const [name, setName] = useState(role?.name ?? '')
  const [perms, setPerms] = useState<Set<string>>(() => new Set(role?.permissions ?? []))
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS)
  const formRef = useRef<HTMLFormElement>(null)
  useFocusInvalid(formRef, errors)
  const save = useMutation({
    mutationFn: (body: { name: string; permissions: string[] }) =>
      role ? api.patch<Role>(`/roles/${String(role.id)}/`, body) : api.post<Role>('/roles/', body),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['roles'] })
      onClose()
    },
    onError: (error) => { setErrors(serverErrors(error, t, (path) => path === 'name' || path === 'permissions')) },
  })

  const submit = () => {
    if (readOnlyRole) return
    if (!name.trim()) {
      setErrors({ fields: { name: t('errors.requiredField') }, banner: undefined })
      return
    }
    setErrors(NO_ERRORS)
    save.mutate({ name: name.trim(), permissions: ALL_CODES.filter((c) => perms.has(c)) })
  }
  const toggle = (code: string) => {
    setPerms((prev) => {
      const next = new Set(prev)
      if (next.has(code)) next.delete(code)
      else next.add(code)
      return next
    })
  }

  return (
    <Drawer
      open
      width="max-w-2xl"
      title={role ? (readOnlyRole ? t('roles.viewTitle', { name: role.name }) : t('roles.edit')) : t('roles.new')}
      onClose={onClose}
      busy={save.isPending}
      footer={
        <>
          <Button onClick={onClose} disabled={save.isPending}>{readOnlyRole ? t('common.close') : t('common.cancel')}</Button>
          {readOnlyRole ? null : (
            <WriteButton permission={editing ? 'roles.update' : 'roles.create'} variant="primary" onClick={submit} disabled={save.isPending}>
              {save.isPending ? t('common.saving') : t('common.save')}
            </WriteButton>
          )}
        </>
      }
    >
      <form ref={formRef} noValidate className="space-y-3" onSubmit={(event) => { event.preventDefault(); if (canSave) submit() }}>
        <FormBanner message={errors.banner} />
        {readOnlyRole ? <Banner kind="info">{t('roles.systemReadonly')}</Banner> : null}
        <TextField label={t('roles.name')} required value={name} disabled={readOnlyRole} error={errors.fields.name} onChange={(e) => { setName(e.target.value) }} />
        {errors.fields.permissions ? <p role="alert" className="text-xs text-red-600">{errors.fields.permissions}</p> : null}
        <p className="text-xs text-slate-500">{t('roles.grantRule')}</p>
        <div className="overflow-x-auto rounded border border-slate-200 dark:border-slate-700">
          <table className="w-full min-w-max text-sm">
            <caption className="sr-only">{t('roles.matrix')}</caption>
            <thead className="bg-slate-50 text-xs dark:bg-slate-800">
              <tr>
                <th scope="col" className="px-2 py-1 text-left font-medium">{t('roles.section')}</th>
                {ACTIONS.map((a) => <th key={a} scope="col" className="px-2 py-1 text-center font-medium">{t(`roles.actions.${a}`)}</th>)}
              </tr>
            </thead>
            <tbody>
              {SECTIONS.map((section) => (
                <tr key={section} className="border-t border-slate-100 dark:border-slate-800">
                  <th scope="row" className="px-2 py-1 text-left font-normal">{t(`roles.sections.${section}`)}</th>
                  {ACTIONS.map((action) => {
                    const code = `${section}.${action}`
                    const held = hasPermission(code)
                    const label = `${t(`roles.sections.${section}`)}: ${t(`roles.actions.${action}`)}`
                    return (
                      <td key={action} className="px-2 py-0.5 text-center">
                        <input
                          type="checkbox"
                          className="h-4 w-4 accent-brand-600"
                          aria-label={label}
                          checked={perms.has(code)}
                          disabled={readOnlyRole || !held}
                          title={!readOnlyRole && !held ? t('roles.cannotGrant') : undefined}
                          onChange={() => { toggle(code) }}
                        />
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <fieldset className="space-y-1">
          <legend className="text-xs font-medium">{t('roles.extra.title')}</legend>
          {[...EXTRA_CODES, ...MODULE_CODES].map((code) => {
            const held = hasPermission(code)
            return (
              <Checkbox
                key={code}
                label={t(`roles.extra.${code}`)}
                checked={perms.has(code)}
                disabled={readOnlyRole || !held}
                title={!readOnlyRole && !held ? t('roles.cannotGrant') : undefined}
                onChange={() => { toggle(code) }}
              />
            )
          })}
        </fieldset>
      </form>
    </Drawer>
  )
}
