import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { I18nextProvider } from 'react-i18next'
import { describe, expect, it } from 'vitest'
import i18n from '../i18n'
import { Drawer } from './Drawer'

function Harness() {
  const [open, setOpen] = useState(false)
  return (
    <I18nextProvider i18n={i18n}>
      <button onClick={() => { setOpen(true) }}>Открыть</button>
      <Drawer open={open} title="Панель" onClose={() => { setOpen(false) }} footer={<button>Готово</button>}>
        <input aria-label="Поле" />
      </Drawer>
    </I18nextProvider>
  )
}

describe('Drawer/Dialog', () => {
  it('фокус внутрь, Tab не уходит наружу, Escape закрывает и возвращает фокус', async () => {
    render(<Harness />)
    const opener = screen.getByRole('button', { name: 'Открыть' })
    await userEvent.click(opener)
    const dialog = screen.getByRole('dialog', { name: 'Панель' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(dialog.contains(document.activeElement)).toBe(true)
    for (let i = 0; i < 6; i++) {
      await userEvent.tab()
      expect(dialog.contains(document.activeElement)).toBe(true)
    }
    await userEvent.tab({ shift: true })
    expect(dialog.contains(document.activeElement)).toBe(true)
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(opener).toHaveFocus()
  })
})
