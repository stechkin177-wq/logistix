"""Row-Level Security в PostgreSQL - вторая линия изоляции компаний.

Первая линия - менеджер ``TenantModel.objects`` (фильтр по контексту компании). Вторая -
политика ``tenant_isolation`` на каждой таблице ``TenantModel``::

    USING      (company_id = NULLIF(current_setting('app.company_id', true), '')::int)
    WITH CHECK (то же выражение)

плюс ``ENABLE`` и ``FORCE ROW LEVEL SECURITY`` (FORCE подчиняет политике и владельца
таблиц). Без ``app.company_id`` (не задан или пустая строка) выражение даёт NULL: строк
не видно и записать ничего нельзя (fail closed). Суперпользователь и роль с BYPASSRLS
политику обходят ВСЕГДА, поэтому приложение в продакшене подключается ролью
NOSUPERUSER NOBYPASSRLS (проверка: ``manage.py check_rls``).

Синхронизация GUC. ``tenancy.set_current_company`` к БД не обращается (чистые
unit-тесты, запрет БД в pytest-django). Вместо этого на каждое соединение ставится
обёртка ``execute_wrappers``: перед каждым запросом она сравнивает значение, последним
выставленное на этом соединении, с ``get_current_company_id()`` и только при
расхождении выполняет ``SELECT set_config('app.company_id', %s, false)`` на сыром
курсоре psycopg (мимо обёрток, без рекурсии). Итог: в момент запроса GUC всегда равен
контекстной переменной, устаревшее значение предыдущего запроса не используется, лишнего
запроса без смены компании нет.

Откаты. В PostgreSQL ``set_config(..., false)`` (как и ``SET``) внутри транзакции,
которая затем откатывается (ROLLBACK или ROLLBACK TO SAVEPOINT), ОТМЕНЯЕТСЯ - проверено
на PostgreSQL 16. Поэтому ``rollback()`` и ``savepoint_rollback()`` соединения
забывают запомненное значение, и следующий запрос выставляет GUC заново. COMMIT и
RELEASE SAVEPOINT значение сохраняют. Новое (пере)подключение, в том числе из пула,
начинает с «неизвестно» (сигнал ``connection_created``). Каждый поток имеет своё
соединение и свою контекстную переменную. ``ATOMIC_REQUESTS``, постоянные соединения
(``CONN_MAX_AGE``) и ``select_for_update`` работают как прежде: обёртка только добавляет
``set_config`` перед запросом, когда компания сменилась.

Не покрывается: SQL мимо курсоров Django (``connection.connection.cursor()``) и ручной
``ROLLBACK``/``SET`` через курсор - такой код обязан сам позаботиться о GUC.

Принятый пробел: Company, User, Membership, Subscription, Plan и CompanyBranding - не
TenantModel и RLS не имеют: их читают до появления контекста компании (вход, аутентификация,
шлюз подписки, публичный эндпоинт оформления экрана входа).
Их изоляция обеспечивается только кодом.

ПУЛЕРЫ СОЕДИНЕНИЙ: PgBouncer в режимах transaction и statement НЕ ПОДДЕРЖИВАЕТСЯ - параметр
``app.company_id`` живёт на уровне сессии PostgreSQL, а клиентский кэш считает его значение
привязанным к соединению; соединение, подменённое пулером между запросами, даёт чужую или
пустую компанию. Допустимы прямое подключение и PgBouncer только в режиме session.

Новые таблицы ``TenantModel`` в миграциях модулей::

    from apps.core.rls import EnableRLS
    operations = [migrations.CreateModel(...), EnableRLS("forwarding.Client")]

Страж ``tests/test_rls.py::test_every_tenant_table_has_rls`` (``tables_missing_rls()``)
падает, если таблица какой-либо TenantModel осталась без RLS.
"""

from django.db import connection as default_connection
from django.db.backends.signals import connection_created
from django.db.migrations.operations.base import Operation
from psycopg.pq import TransactionStatus

from .tenancy import get_current_company_id

POLICY_NAME = "tenant_isolation"
GUC_NAME = "app.company_id"
EXCLUDED_APP_LABELS = ("core_tests",)  # тестовые модели: таблицы вне цепочки миграций

_EXPR = f"company_id = NULLIF(current_setting('{GUC_NAME}', true), '')::int"
_UNKNOWN = object()
_STATE_ATTR = "_logistix_rls_synced"
_INSTALLED_ATTR = "_logistix_rls_installed"


def _quote(table: str) -> str:
    return '"%s"' % table.replace('"', '""')


def enable_rls(table: str) -> list[str]:
    """SQL включения RLS и политики tenant_isolation на таблице (идемпотентно)."""
    t = _quote(table)
    return [
        f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY",
        f"DROP POLICY IF EXISTS {POLICY_NAME} ON {t}",
        f"CREATE POLICY {POLICY_NAME} ON {t} USING ({_EXPR}) WITH CHECK ({_EXPR})",
    ]


def disable_rls(table: str) -> list[str]:
    """SQL, обратный enable_rls."""
    t = _quote(table)
    return [
        f"DROP POLICY IF EXISTS {POLICY_NAME} ON {t}",
        f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY",
        f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY",
    ]


class EnableRLS(Operation):
    """Операция миграции: RLS на таблице модели ("app.Model") или таблице по имени.

    Обратимая: откат миграции снимает политику и RLS. На других СУБД ничего не делает.
    """

    reversible = True
    reduces_to_sql = True

    def __init__(self, model_label_or_table: str):
        self.target = model_label_or_table

    def deconstruct(self):
        return (f"{__name__}.{type(self).__name__}", [self.target], {})

    def state_forwards(self, app_label, state):
        pass

    def _table(self, state):
        if "." not in self.target:
            return self.target
        return state.apps.get_model(self.target)._meta.db_table

    def _run(self, schema_editor, statements):
        if schema_editor.connection.vendor != "postgresql":
            return
        for sql in statements:
            schema_editor.execute(sql)

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        self._run(schema_editor, enable_rls(self._table(to_state)))

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        self._run(schema_editor, disable_rls(self._table(from_state)))

    def describe(self):
        return f"Включить RLS ({POLICY_NAME}) для {self.target}"

    @property
    def migration_name_fragment(self):
        return f"rls_{self.target.replace('.', '_').lower()}"


# --- проверка покрытия -----------------------------------------------------------------


def tenant_tables() -> list[str]:
    """Таблицы конкретных моделей TenantModel (кроме тестового приложения core_tests)."""
    from django.apps import apps

    from .models import TenantModel

    tables = {
        m._meta.db_table
        for m in apps.get_models()
        if issubclass(m, TenantModel)
        and not m._meta.abstract
        and not m._meta.proxy
        and m._meta.managed
        and m._meta.app_label not in EXCLUDED_APP_LABELS
    }
    return sorted(tables)


def tables_missing_rls(tables=None, connection=None) -> list[str]:
    """Таблицы без ENABLE + FORCE RLS или без политики tenant_isolation (с USING и
    WITH CHECK по app.company_id). По умолчанию проверяются все tenant_tables()."""
    conn = connection or default_connection
    tables = sorted(tenant_tables() if tables is None else tables)
    if not tables:
        return []
    with conn.cursor() as c:
        c.execute(
            """
            SELECT c.relname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = current_schema()
              AND c.relkind IN ('r', 'p')
              AND c.relname = ANY(%s)
              AND c.relrowsecurity AND c.relforcerowsecurity
              AND EXISTS (
                SELECT 1 FROM pg_policies p
                WHERE p.schemaname = n.nspname AND p.tablename = c.relname
                  AND p.policyname = %s AND p.cmd = 'ALL'
                  AND p.permissive = 'PERMISSIVE'
                  AND p.qual LIKE %s AND p.with_check LIKE %s
              )
            """,
            [tables, POLICY_NAME, f"%{GUC_NAME}%", f"%{GUC_NAME}%"],
        )
        ok = {row[0] for row in c.fetchall()}
    return [t for t in tables if t not in ok]


def connected_role_problems(connection=None) -> list[str]:
    """Причины, по которым текущая роль обходит RLS (суперпользователь, BYPASSRLS)."""
    conn = connection or default_connection
    with conn.cursor() as c:
        c.execute(
            "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )
        user, is_super, bypass = c.fetchone()
    problems = []
    if is_super:
        problems.append(f"роль {user} - суперпользователь (RLS не действует)")
    if bypass:
        problems.append(f"у роли {user} есть BYPASSRLS (RLS не действует)")
    return problems


# --- синхронизация app.company_id ----------------------------------------------------------


def _set_guc(connection, company_id) -> None:
    value = "" if company_id is None else str(company_id)
    with connection.wrap_database_errors:
        with connection.connection.cursor() as cur:  # сырой курсор: мимо execute_wrappers
            cur.execute("SELECT set_config(%s, %s, false)", [GUC_NAME, value])


def _forget(connection) -> None:
    setattr(connection, _STATE_ATTR, _UNKNOWN)


def sync_guc(connection) -> None:
    """Выставляет app.company_id = текущая компания, если на соединении оно другое.

    В прерванной транзакции (ошибка, ждём ROLLBACK) ничего не делает: запрос либо сам
    упадёт с ошибкой Django/PostgreSQL, либо это ROLLBACK [TO SAVEPOINT], после которого
    значение будет выставлено заново.
    """
    if connection.needs_rollback:
        return
    if connection.connection.info.transaction_status == TransactionStatus.INERROR:
        return
    company_id = get_current_company_id()
    if getattr(connection, _STATE_ATTR, _UNKNOWN) == company_id:
        return
    _forget(connection)  # если set_config упадёт, значение останется «неизвестным»
    _set_guc(connection, company_id)
    setattr(connection, _STATE_ATTR, company_id)


def _make_wrapper(connection):
    def rls_execute_wrapper(execute, sql, params, many, context):
        sync_guc(connection)
        return execute(sql, params, many, context)

    return rls_execute_wrapper


def _patch_rollbacks(connection) -> None:
    """Откат транзакции или точки сохранения отменяет и set_config - забываем значение."""
    rollback = connection.rollback
    savepoint_rollback = connection.savepoint_rollback

    def rollback_and_forget():
        try:
            return rollback()
        finally:
            _forget(connection)

    def savepoint_rollback_and_forget(sid):
        try:
            return savepoint_rollback(sid)
        finally:
            _forget(connection)

    connection.rollback = rollback_and_forget
    connection.savepoint_rollback = savepoint_rollback_and_forget


def install(connection) -> None:
    """Ставит синхронизацию на объект соединения (идемпотентно) и сбрасывает состояние."""
    _forget(connection)
    if connection.vendor != "postgresql" or getattr(connection, _INSTALLED_ATTR, False):
        return
    # В начало списка: connection.execute_wrapper() снимает последний элемент (pop()),
    # и наш обёртчик, поставленный внутри чужого блока, не должен быть снят вместо него.
    connection.execute_wrappers.insert(0, _make_wrapper(connection))
    _patch_rollbacks(connection)
    setattr(connection, _INSTALLED_ATTR, True)


def _on_connection_created(sender, connection, **kwargs):
    install(connection)


connection_created.connect(_on_connection_created, dispatch_uid="logistix_rls_install")
