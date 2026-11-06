from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS, connections

from apps.core import rls


class Command(BaseCommand):
    help = (
        "Проверяет, что RLS действует: роль подключения не суперпользователь и без "
        "BYPASSRLS, а у каждой таблицы TenantModel включены RLS + FORCE и политика "
        "tenant_isolation. Код выхода не 0 при любой проблеме."
    )

    def add_arguments(self, parser):
        parser.add_argument("--database", default=DEFAULT_DB_ALIAS)

    def handle(self, *args, database, **options):
        connection = connections[database]
        problems = rls.connected_role_problems(connection)
        missing = rls.tables_missing_rls(connection=connection)
        if missing:
            problems.append("таблицы без RLS: " + ", ".join(missing))
        if problems:
            raise CommandError("RLS не защищает данные: " + "; ".join(problems))
        self.stdout.write(
            self.style.SUCCESS(f"RLS в порядке: {len(rls.tenant_tables())} таблиц компаний")
        )
