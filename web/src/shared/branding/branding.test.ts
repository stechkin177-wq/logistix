import { describe, expect, it } from 'vitest'
import { applyBranding, safeAppName, safeLogoUrl } from './applyBranding'
import { SHADE_KEYS, shadeScale } from './palette'

const root = document.documentElement
const brand500 = () => root.style.getPropertyValue('--brand-500')

function luminance(hex: string): number {
  const [r = 0, g = 0, b = 0] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

describe('shadeScale', () => {
  it('возвращает 11 оттенков от светлого к тёмному, 500 - исходный цвет', () => {
    const scale = shadeScale('#2563eb')
    expect(Object.keys(scale)).toHaveLength(11)
    expect(scale[500]).toBe('#2563eb')
    const lum = SHADE_KEYS.map((k) => luminance(scale[k]))
    for (let i = 1; i < lum.length; i++) expect(lum[i]).toBeLessThan(lum[i - 1] ?? 0)
    for (const k of SHADE_KEYS) expect(scale[k]).toMatch(/^#[0-9a-f]{6}$/i)
  })

  it('мусор заменяется цветом по умолчанию', () => {
    expect(shadeScale('red; background:url(x)')[500]).toBe('#2563eb')
  })
})

describe('applyBranding', () => {
  it('выставляет --brand-500 ровно равным входному цвету', () => {
    applyBranding({ primary_color: '#2563eb' })
    expect(brand500()).toBe('#2563eb')
    expect(root.style.getPropertyValue('--brand-50')).toMatch(/^#[0-9a-f]{6}$/)
    expect(root.style.getPropertyValue('--brand-950')).toMatch(/^#[0-9a-f]{6}$/)
  })

  it('игнорирует мусорный цвет и не пишет его в CSS', () => {
    applyBranding({ primary_color: 'url(javascript:alert(1))' })
    expect(brand500()).toBe('#2563eb')
    applyBranding({ primary_color: '#12345' })
    expect(brand500()).toBe('#2563eb')
    applyBranding({ primary_color: 42 })
    expect(brand500()).toBe('#2563eb')
  })

  it('переключает класс dark по теме', () => {
    applyBranding({ theme: 'dark' })
    expect(root.classList.contains('dark')).toBe(true)
    applyBranding({ theme: 'light' })
    expect(root.classList.contains('dark')).toBe(false)
  })

  it('theme=system следует за prefers-color-scheme', () => {
    let listener: ((e: { matches: boolean }) => void) | undefined
    window.matchMedia = ((query: string) => ({
      matches: true,
      media: query,
      addEventListener: (_: string, fn: (e: { matches: boolean }) => void) => {
        listener = fn
      },
      removeEventListener: () => undefined,
    })) as unknown as typeof window.matchMedia
    applyBranding({ theme: 'system' })
    expect(root.classList.contains('dark')).toBe(true)
    listener?.({ matches: false })
    expect(root.classList.contains('dark')).toBe(false)
    // @ts-expect-error возвращаем окружение jsdom без matchMedia
    delete window.matchMedia
  })

  it('app_name попадает в document.title как текст', () => {
    applyBranding({ app_name: '  <b>Моя Логистика</b>  ' })
    expect(document.title).toBe('<b>Моя Логистика</b>')
    applyBranding({ app_name: '' })
    expect(document.title).toBe('Logistix')
  })
})

describe('безопасные значения', () => {
  it('logo_url: только / или http(s)', () => {
    expect(safeLogoUrl('/media/branding/a.png')).toBe('/media/branding/a.png')
    expect(safeLogoUrl('https://cdn.example.kz/a.png')).toBe('https://cdn.example.kz/a.png')
    expect(safeLogoUrl('javascript:alert(1)')).toBeNull()
    expect(safeLogoUrl('data:image/svg+xml,<svg/>')).toBeNull()
    expect(safeLogoUrl('//evil.example/x.png')).toBeNull()
    expect(safeLogoUrl(null)).toBeNull()
    // браузер вырезает \t и \n в URL: "/\t/evil" превратился бы в "//evil"
    for (const bad of ['/\t/evil.com/x.png', '/\n/evil.com/x.png', '/\r/evil.com/x.png', ' /a.png', '/a b.png', 'https://a.kz/\u0000x', '/a\u007f.png']) {
      expect(safeLogoUrl(bad), JSON.stringify(bad)).toBeNull()
    }
  })

  it('app_name обрезается и очищается от управляющих символов', () => {
    expect(safeAppName('A\u0000B')).toBe('AB')
    expect(safeAppName('x'.repeat(200))).toHaveLength(64)
    expect(safeAppName(5)).toBe('Logistix')
  })
})
