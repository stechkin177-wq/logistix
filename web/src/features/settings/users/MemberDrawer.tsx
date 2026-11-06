import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../../../shared/api/client'
import { ApiError } from '../../../shared/api/errors'
import { useCanWrite } from '../../../shared/auth/useCanWrite'
import { NO_ERRORS, serverErrors, type FormErrors } from '../../../shared/forms/serverErrors'
import { useFocusInvalid } from '../../../shared/forms/useFocusInvalid'
import { Banner } from '../../../shared/ui/Banner'
import { Button } from '../../../shared/ui/Button'
import { Checkbox } from '../../../shared/ui/Checkbox'
import { Drawer } from '../../../shared/ui/Drawer'
import { FormBanner } from '../../../shared/ui/FormBanner'
import { Select } from '../../../shared/ui/Select'
import { TextField } from '../../../shared/ui/TextField'
import { pushToast } from '../../../shared/ui/toast'
import { WriteButton } from '../../../shared/ui/WriteButton'
import { userLabel, type CompanyUser } from '../../../shared/users/useUsers'
import { useDepartments } from '../departments/useDepartments'
import { useRoles } from '../roles/RolesPage'

interface CreateResult {
  id: number
  /** Есть только у присоединённого существующего пользователя (профиль чужого аккаунта не раскрывается). */
  login?: string
  full_name?: string
}

/** Новый сотрудник или присоединение существующего пользователя (по логину решает сервер); правка роли/отдела/активности. */
export function MemberDrawer({ member, onClose }: { member: CompanyUser | null; onClose: () => void }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const editing = member !== null
  const canSave = useCanWrite(editing ? 'users.update' : 'users.create')
  const roles = useRoles()
  const { departments } = useDepartments()
  const [login, setLogin] = useState('')
  const [fullName, setFullName] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState(member?.role != null ? String(member.role) : '')
  const [department, setDepartment] = useState(member?.department != null ? String(member.department) : '')
  const [active, setActive] = useState(member?.is_active ?? true)
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS)
  const formRef = useRef<HTMLFormElement>(null)
  useFocusInvalid(formRef, errors)

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      member ? api.patch<unknown>(`/users/${String(member.id)}/`, body) : api.post<CreateResult>('/users/', body),
    onSuccess: async (result) => {
      await Promise.all([qc.invalidateQueries({ queryKey: ['users'] }), qc.invalidateQueries({ queryKey: ['roles'] })])
      if (!editing) {
        const created = result as CreateResult
        pushToast('info', created.login !== undefined && created.full_name === undefined ? t('users.attached', { login: created.login }) : t('users.created'))
      }
      onClose()
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === 'limit_exceeded') {
        setErrors({ fields: {}, banner: t('users.limitExceeded') })
        return
      }
      setErrors(serverErrors(error, t, (p) => ['login', 'password', 'full_name', 'role', 'department', 'is_active'].includes(p)))
    },
  })

  const submit = () => {
    const local: Record<string, string> = {}
    if (!editing && !login.trim()) local.login = t('errors.requiredField')
    if (!editing && !password) local.password = t('errors.requiredField')
    if (!role) local.role = t('errors.requiredField')
    if (Object.keys(local).length > 0) {
      setErrors({ fields: local, banner: undefined })
      return
    }
    setErrors(NO_ERRORS)
    if (member) {
      // только изменившиеся поля: лишний role для самого себя сервер отвергает
      const body: Record<string, unknown> = {}
      if (role !== String(member.role ?? '')) body.role = Number(role)
      if (department !== String(member.department ?? '')) body.department = department ? Number(department) : null
      if (active !== member.is_active) body.is_active = active
      save.mutate(body)
    } else {
      save.mutate({
        login: login.trim(),
        full_name: fullName.trim(),
        role: Number(role),
        department: department ? Number(department) : null,
        password,
      })
    }
  }

  const f = errors.fields
  return (
    <Drawer
      open
      title={member ? t('users.editNamed', { name: userLabel(member) }) : t('users.new')}
      onClose={onClose}
      busy={save.isPending}
      footer={
        <>
          <Button onClick={onClose} disabled={save.isPending}>{t('common.cancel')}</Button>
          <WriteButton permission={editing ? 'users.update' : 'users.create'} variant="primary" onClick={submit} disabled={save.isPending}>
            {save.isPending ? t('common.saving') : t('common.save')}
          </WriteButton>
        </>
      }
    >
      <form ref={formRef} noValidate className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (canSave) submit() }}>
        <FormBanner message={errors.banner} />
        {editing ? null : (
          <>
            <Banner kind="info">{t('users.attachHint')}</Banner>
            <TextField label={t('users.login')} required value={login} error={f.login} hint={t('users.loginHint')} autoComplete="off" onChange={(e) => { setLogin(e.target.value) }} />
            <TextField label={t('users.fullName')} value={fullName} error={f.full_name} onChange={(e) => { setFullName(e.target.value) }} />
            <TextField label={t('users.password')} type="password" required value={password} error={f.password} hint={t('users.passwordHint')} autoComplete="new-password" onChange={(e) => { setPassword(e.target.value) }} />
          </>
        )}
        <Select
          label={t('users.role')}
          required
          value={role}
          placeholder={t('common.none')}
          error={f.role}
          disabled={roles.isError}
          options={(roles.data ?? []).map((r) => ({ value: String(r.id), label: r.name }))}
          onChange={setRole}
        />
        {roles.isError ? <p className="text-xs text-amber-700">{t('users.rolesUnavailable')}</p> : null}
        <Select
          label={t('users.department')}
          value={department}
          placeholder={t('common.none')}
          error={f.department}
          options={departments.map((d) => ({ value: String(d.id), label: d.name }))}
          onChange={setDepartment}
        />
        {editing ? <Checkbox label={t('users.activeLabel')} checked={active} onChange={(e) => { setActive(e.target.checked) }} /> : null}
        {f.is_active ? <p role="alert" className="text-xs text-red-600">{f.is_active}</p> : null}
      </form>
    </Drawer>
  )
}
