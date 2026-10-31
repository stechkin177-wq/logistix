-- Инициализация БД (docker-compose: /docker-entrypoint-initdb.d, CI: psql -f).
-- Выполняется владельцем БД (logistix), до миграций.
--
-- Роли:
--   logistix      - владелец таблиц, под ним идут миграции (manage.py migrate).
--   logistix_app  - роль, которой подключается приложение (DATABASE_URL в продакшене):
--                   NOSUPERUSER NOBYPASSRLS, только DML. FORCE ROW LEVEL SECURITY
--                   подчиняет политике tenant_isolation и владельца, но суперпользователь
--                   и роль с BYPASSRLS RLS обходят всегда - приложение под ними в
--                   продакшене не запускать (проверка: manage.py check_rls).
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'logistix_app') THEN
    CREATE ROLE logistix_app LOGIN PASSWORD 'logistix_app'
      NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
  ELSE
    ALTER ROLE logistix_app NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
  END IF;
END
$$;

GRANT CONNECT, TEMPORARY ON DATABASE logistix TO logistix_app;
GRANT USAGE ON SCHEMA public TO logistix_app;

-- Уже созданные таблицы и последовательности.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO logistix_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO logistix_app;

-- Таблицы, которые миграции владельца создадут позже.
ALTER DEFAULT PRIVILEGES FOR ROLE logistix IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO logistix_app;
ALTER DEFAULT PRIVILEGES FOR ROLE logistix IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO logistix_app;
