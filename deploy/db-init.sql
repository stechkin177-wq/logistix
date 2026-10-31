-- Роль приложения без прав суперпользователя (нужна для RLS).
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'logistix_app') THEN
    CREATE ROLE logistix_app LOGIN PASSWORD 'logistix_app';
  END IF;
END
$$;
GRANT ALL PRIVILEGES ON DATABASE logistix TO logistix_app;
