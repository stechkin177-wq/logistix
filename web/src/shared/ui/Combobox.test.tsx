import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { I18nextProvider } from 'react-i18next'
import { describe, expect, it, vi } from 'vitest'
import i18n from '../i18n'
import { Combobox, type ComboOption } from './Combobox'

function Harness({ fetchOptions }: { fetchOptions: (q: string, s: AbortSignal) => Promise<ComboOption[]> }) {
  const [value, setValue] = useState<ComboOption | null>(null)
  return (
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <Combobox label="Клиент" value={value} onChange={setValue} fetchOptions={fetchOptions} queryKey={['t']} debounceMs={10} />
      </QueryClientProvider>
    </I18nextProvider>
  )
}

describe('Combobox', () => {
  it('ищет на сервере по введённому тексту, выбирается с клавиатуры, очищается', async () => {
    const fetchOptions = vi.fn((q: string) => Promise.resolve(q === 'ро' ? [{ id: 1, label: 'Ромашка' }, { id: 2, label: 'Рога' }] : [{ id: 3, label: 'Все' }]))
    render(<Harness fetchOptions={fetchOptions} />)
    const input = screen.getByRole('combobox', { name: 'Клиент' })
    await userEvent.type(input, 'ро')
    expect(await screen.findByRole('option', { name: 'Ромашка' })).toBeInTheDocument()
    expect(fetchOptions.mock.calls.some(([q]) => q === 'ро')).toBe(true)
    await userEvent.keyboard('{ArrowDown}{Enter}')
    await waitFor(() => { expect(input).toHaveValue('Рога') })
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Очистить' }))
    expect(input).toHaveValue('')
  })

  it('ошибка загрузки показывается в списке, пустой результат - «ничего не найдено»', async () => {
    const fail = vi.fn(() => Promise.reject(new Error('x')))
    render(<Harness fetchOptions={fail} />)
    await userEvent.click(screen.getByRole('combobox', { name: 'Клиент' }))
    expect(await screen.findByText('Не удалось загрузить данные')).toBeInTheDocument()
  })

  it('Escape закрывает список, но не внешнее окно', async () => {
    render(<Harness fetchOptions={() => Promise.resolve([])} />)
    await userEvent.click(screen.getByRole('combobox', { name: 'Клиент' }))
    expect(await screen.findByText('Ничего не найдено')).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })
})
