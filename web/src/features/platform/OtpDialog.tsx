import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../../shared/api/client'
import { errorMessage } from '../../shared/api/errors'
import { Banner } from '../../shared/ui/Banner'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { Spinner } from '../../shared/ui/Spinner'
import { TextField } from '../../shared/ui/TextField'

interface OtpState { otp_required: boolean; otp_connected: boolean }
const KEY = ['platform-otp'] as const

/** Вход владельца платформы с кодом OTP или без: включается сразу, отключается кодом из приложения. */
export function OtpDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const state = useQuery({ queryKey: KEY, queryFn: ({ signal }) => api.get<OtpState>('/platform/otp/', undefined, { signal }) })
  const [code, setCode] = useState('')
  const change = useMutation({
    mutationFn: (required: boolean) => api.post<OtpState>('/platform/otp/', required ? { required } : { required, code: code.trim() }),
    onSuccess: (next) => { qc.setQueryData(KEY, next); setCode('') },
  })
  const required = state.data?.otp_required ?? true
  return (
    <Dialog open title={t('platformShell.otp.title')} onClose={onClose} busy={change.isPending} footer={<Button onClick={onClose}>{t('common.close')}</Button>}>
      <div className="space-y-3">
        {state.isPending ? <Spinner /> : null}
        {state.isError ? <Banner kind="error">{errorMessage(state.error, t)}</Banner> : null}
        {state.data ? (
          <>
            <Banner kind={required ? 'info' : 'warning'}>{required ? t('platformShell.otp.on') : t('platformShell.otp.off')}</Banner>
            {change.isError ? <Banner kind="error">{errorMessage(change.error, t)}</Banner> : null}
            {required ? (
              <>
                <p className="text-sm text-muted">{t('platformShell.otp.disableHint')}</p>
                <TextField label={t('platformShell.otp.code')} inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => { setCode(e.target.value.replace(/\D/g, '').slice(0, 6)) }} />
                <Button variant="dangerSoft" disabled={change.isPending || code.length !== 6} onClick={() => { change.mutate(false) }}>{t('platformShell.otp.disable')}</Button>
              </>
            ) : (
              <>
                <p className="text-sm text-muted">{t('platformShell.otp.enableHint')}</p>
                <Button variant="primary" disabled={change.isPending} onClick={() => { change.mutate(true) }}>{t('platformShell.otp.enable')}</Button>
              </>
            )}
          </>
        ) : null}
      </div>
    </Dialog>
  )
}
