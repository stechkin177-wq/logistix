export const SHADE_KEYS = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950] as const
export type ShadeKey = (typeof SHADE_KEYS)[number]

const HEX_RE = /^#[0-9a-fA-F]{6}$/

export const DEFAULT_COLOR = '#2563eb'

export function isHexColor(value: unknown): value is string {
  return typeof value === 'string' && HEX_RE.test(value)
}

interface Hsl {
  h: number
  s: number
  l: number
}

function hexToHsl(hex: string): Hsl {
  const r = parseInt(hex.slice(1, 3), 16) / 255
  const g = parseInt(hex.slice(3, 5), 16) / 255
  const b = parseInt(hex.slice(5, 7), 16) / 255
  const max = Math.max(r, g, b)
  const min = Math.min(r, g, b)
  const l = (max + min) / 2
  const d = max - min
  if (d === 0) return { h: 0, s: 0, l: l * 100 }
  const s = d / (1 - Math.abs(2 * l - 1))
  let h: number
  if (max === r) h = ((g - b) / d) % 6
  else if (max === g) h = (b - r) / d + 2
  else h = (r - g) / d + 4
  return { h: (h * 60 + 360) % 360, s: s * 100, l: l * 100 }
}

function hslToHex({ h, s, l }: Hsl): string {
  const sat = s / 100
  const light = l / 100
  const a = sat * Math.min(light, 1 - light)
  const channel = (n: number): string => {
    const k = (n + h / 30) % 12
    const value = light - a * Math.max(-1, Math.min(k - 3, 9 - k, 1))
    return Math.round(value * 255)
      .toString(16)
      .padStart(2, '0')
  }
  return `#${channel(0)}${channel(8)}${channel(4)}`
}

// доля пути от базового оттенка к самому светлому (97%) и к тёмному (множитель яркости)
const LIGHTER: Record<50 | 100 | 200 | 300 | 400, number> = {
  50: 1,
  100: 0.9,
  200: 0.75,
  300: 0.55,
  400: 0.3,
}
const DARKER: Record<600 | 700 | 800 | 900 | 950, number> = {
  600: 0.85,
  700: 0.7,
  800: 0.55,
  900: 0.4,
  950: 0.25,
}

/** Шкала оттенков 50..950 из #RRGGBB; 500 - ровно исходный цвет. Мусор -> шкала цвета по умолчанию. */
export function shadeScale(hex: string): Record<ShadeKey, string> {
  const base = isHexColor(hex) ? hex : DEFAULT_COLOR
  const { h, s, l } = hexToHsl(base)
  const baseL = Math.min(l, 90)
  const at = (lightness: number): string => hslToHex({ h, s, l: lightness })
  return {
    50: at(baseL + (97 - baseL) * LIGHTER[50]),
    100: at(baseL + (97 - baseL) * LIGHTER[100]),
    200: at(baseL + (97 - baseL) * LIGHTER[200]),
    300: at(baseL + (97 - baseL) * LIGHTER[300]),
    400: at(baseL + (97 - baseL) * LIGHTER[400]),
    500: base,
    600: at(baseL * DARKER[600]),
    700: at(baseL * DARKER[700]),
    800: at(baseL * DARKER[800]),
    900: at(baseL * DARKER[900]),
    950: at(baseL * DARKER[950]),
  }
}
