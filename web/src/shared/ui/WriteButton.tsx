import { useTranslation } from 'react-i18next'
import { useWriteBlockReason } from '../auth/useCanWrite'
import { Button, type ButtonProps } from './Button'

/** Кнопка записи: отключается без права или в режиме только чтения (с пояснением в title). */
export function WriteButton({ permission, disabled, title, ...rest }: ButtonProps & { permission?: string }) {
  const { t } = useTranslation()
  const reason = useWriteBlockReason(permission)
  const hint =
    reason === 'readonly' ? t('readonly.writeDisabled') : reason === 'permission' ? t('common.noPermission') : undefined
  return <Button {...rest} disabled={disabled || reason !== null} title={hint ?? title} />
}
