"""Защита от подключения через пулер PgBouncer в транзакционном/операторном режиме.

RLS опирается на сессионный GUC ``app.company_id``. Транзакционный пулер отдаёт одно
серверное соединение разным клиентам, и настройка одной компании может «протечь» в запрос
другой - это утечка данных между арендаторами. Поэтому такие URL запрещены.
Модуль не зависит от настроек Django (импортируется и тестируется отдельно).
"""

from urllib.parse import parse_qs, urlsplit

from django.core.exceptions import ImproperlyConfigured

_TRANSACTION_POOLER_PORT = 6543  # Supabase transaction pooler


def pooler_problem(url):
    """Описание проблемы (без пароля) или None, если URL выглядит как прямое/сессионное."""
    if not url:
        return None
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return None
    if "-pooler." in host:
        return f"хост {host!r} - пулер Neon (-pooler)"
    if port == _TRANSACTION_POOLER_PORT:
        return f"порт {_TRANSACTION_POOLER_PORT} - транзакционный пулер (Supabase)"
    values = parse_qs(parts.query).get("pgbouncer", [])
    if any(v.strip().lower() in ("true", "1", "yes", "on") for v in values):
        return "параметр pgbouncer=true в DATABASE_URL"
    return None


def check_database_url(url, *, serverless, debug, pooler_ok):
    """ImproperlyConfigured, если URL - транзакционный пулер, а режим этого не допускает.

    serverless: проверка всегда, DATABASE_POOLER_OK её не отключает;
    иначе в продакшене (debug=False) - пока не задано DATABASE_POOLER_OK=true.
    """
    if not (serverless or (not debug and not pooler_ok)):
        return
    problem = pooler_problem(url)
    if problem is None:
        return
    hint = (
        "Нужна ПРЯМАЯ строка подключения (Neon: без «-pooler» в хосте; Supabase: прямой хост "
        "или session-пулер, порт 5432)."
        if serverless
        else "Если пулер точно работает в сессионном режиме, задайте DATABASE_POOLER_OK=true."
    )
    raise ImproperlyConfigured(
        f"DATABASE_URL указывает на транзакционный пулер ({problem}). Приложение держит "
        "идентификатор компании в сессии PostgreSQL (RLS), а транзакционный/операторный "
        f"пулер PgBouncer смешивает сессии разных компаний - это утечка данных. {hint}"
    )
