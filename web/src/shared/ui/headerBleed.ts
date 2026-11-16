import { createContext } from 'react'

/** Залипающая шапка страницы выступает за поля прокручиваемой области (true) либо стоит ровно в своей колонке (false). */
export const HeaderBleedContext = createContext(true)
