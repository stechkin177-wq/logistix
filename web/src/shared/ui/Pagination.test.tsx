import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { describe, expect, it, vi } from 'vitest'
import i18n from '../i18n'
import { Pagination } from './Pagination'

const setup = (props: Partial<Parameters<typeof Pagination>[0]> = {}) => {
  const onPage = vi.fn()
  render(
    <I18nextProvider i18n={i18n}>
      <Pagination page={2} pageSize={50} count={120} onPage={onPage} {...props} />
    </I18nextProvider>,
  )
  return onPage
}

describe('Pagination', () => {
  it('показывает диапазон и переключает страницы', async () => {
    const onPage = setup()
    expect(screen.getByText('51-100 из 120')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Вперёд' }))
    expect(onPage).toHaveBeenCalledWith(3)
    await userEvent.click(screen.getByRole('button', { name: 'Назад' }))
    expect(onPage).toHaveBeenCalledWith(1)
  })
  it('на границах кнопки отключены; пустой список ничего не рисует', () => {
    setup({ page: 3 })
    expect(screen.getByRole('button', { name: 'Вперёд' })).toBeDisabled()
  })
  it('пустой список', () => {
    setup({ count: 0 })
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
  })
})
