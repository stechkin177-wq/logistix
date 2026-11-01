-- Инициализация БД (docker-compose: /docker-entrypoint-initdb.d, CI: psql -f, restore.sh).
-- Выполняется владельцем БД (logistix), до миграций. Идемпотентен.
--
-- Роли:
--   logistix      - владелец таблиц, под ним идут миграции (manage.py migrate) и бэкапы.
--   logistix_app  - роль, которой подключается приложение (DATABASE_URL в продакшене):
--                   NOSUPERUSER NOBYPASSRLS, только DML. FORCE ROW LEVEL SECURITY
--                   подчиняет политике tenant_isolation и владельца, но суперпользователь
--                   и роль с BYPASSRLS RLS обходят всегда - приложение под ними в
--                   продакшене не запускать (проверка: manage.py check_rls).
--
-- Пароль logistix_app берётся из переменной окружения APP_DB_PASSWORD (psql \getenv, PG 15+).
-- Без неё - пароль РАЗРАБОТКИ 'logistix_app'; в продакшене APP_DB_PASSWORD обязателен.
\set ON_ERROR_STOP on
\getenv app_password APP_DB_PASSWORD
\if :{?app_password}
\else
  \set app_password logistix_app
\endif

SELECT NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'logistix_app') AS need_role \gset
\if :need_role
  CREATE ROLE logistix_app LOGIN PASSWORD :'app_password'
    NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
\else
  ALTER ROLE logistix_app LOGIN PASSWORD :'app_password'
    NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
\endif

-- Имя БД и владельца берутся из текущего подключения (БД может называться не logistix).
SELECT format('GRANT CONNECT, TEMPORARY ON DATABASE %I TO logistix_app', current_database())
\gexec
GRANT USAGE ON SCHEMA public TO logistix_app;

-- Уже созданные таблицы и последовательности.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO logistix_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO logistix_app;

-- Таблицы, которые миграции владельца создадут позже.
SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public '
  'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO logistix_app', current_user)
\gexec
SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public '
  'GRANT USAGE, SELECT ON SEQUENCES TO logistix_app', current_user)
\gexec
