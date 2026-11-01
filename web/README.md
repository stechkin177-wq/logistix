# Logistix web

Фронтенд: React 19, TypeScript (strict), Vite, Tailwind CSS 4, TanStack Query 5,
React Router 7 (data router), i18next. Тесты: Vitest + Testing Library + jsdom.

## Запуск
```bash
cd web
npm ci
npm run dev          # http://localhost:5173
```
Dev-сервер проксирует `/api` и `/media` на `http://127.0.0.1:8000` (бэкенд: `python manage.py runserver`).
Переменных окружения нет: клиент ходит на относительный `/api`.

Проверки (то же, что в CI): `npm run typecheck`, `npm run lint`, `npm test`, `npm run build`.

## Структура (feature-first)
- `src/app/` - `router.tsx` (маршруты из `layout/nav.ts`), `providers.tsx` (QueryClient, i18n), `RootRoute.tsx`
- `src/shared/api/` - `client.ts` (ЕДИНСТВЕННОЕ место с `fetch`), `errors.ts` (`ApiError`), `events.ts`, `types.ts`
- `src/shared/auth/` - токены, `AuthProvider`, `useSession`, `useAuth`, `useCanWrite`, `RequireAuth`
- `src/shared/i18n/` - `ru.json` (источник), `kk.json`, `index.ts`
- `src/shared/branding/` - `applyBranding`, `palette` (шкала `--brand-50..950`), `useBranding`
- `src/shared/ui/` - Button, Input, TextField/TextArea, Select, Combobox (async), DateInput, FormField, Badge, Money, DateTime,
  DataTable (сортировка -> `ordering` API), Pagination (конверт DRF), FilterBar, Overlay/Dialog/Drawer/ConfirmDialog (Escape, trap, возврат фокуса),
  Tabs, Banner, EmptyState, WriteButton, Toaster
- `src/shared/format/` - `formatMoney` (денежные строки без float), даты в поясе компании (`useFormat`)
- `src/shared/hooks/useUrlState.ts` - фильтры/страница/сортировка в адресе (мусор -> значения по умолчанию)
- `src/shared/forms/` - `serverErrors` (ошибки API -> поля формы / баннер), `useFocusInvalid`
- `src/shared/handbooks`, `src/shared/users` - справочники и сотрудники (деградируют без прав)
- `src/layout/` - `AppLayout`, `Sidebar`, `nav.ts` (`visibleNav`), `ReadonlyBanner`
- `src/features/` - `auth` (вход), `dashboard`, `parties` (общий код клиентов и перевозчиков), `clients`, `carriers`, `orders`, `errors` (403/404/«Доступ приостановлен»), `placeholder`
- `src/test/` - помощники тестов (`mockFetch`, `renderApp`, `makeSession`)

## Токены
Access-токен хранится только в памяти, refresh - в `sessionStorage` (переживает перезагрузку,
исчезает при закрытии вкладки). Компромисс: XSS мог бы прочитать refresh; защита - запрет
`dangerouslySetInnerHTML` (lint), валидация брендинга. На этапе 5 refresh планируется перенести в httpOnly-cookie.

## Права и режим подписки
Меню и кнопки только скрываются/отключаются по `GET /api/session/`; доступ проверяет сервер.
Для кнопок записи используйте `<WriteButton permission="...">` или `useCanWrite(permission)`.

## Язык
Строки - через i18next. `ru.json` - источник, `kk.json` обязан иметь тот же набор ключей (проверяет тест).
**Казахские строки переведены приблизительно и требуют проверки носителем языка до релиза.**
