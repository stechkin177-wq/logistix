"""Защита от подключения через пулер PgBouncer в транзакционном/операторном режиме.

RLS опирается на сессионный GUC ``app.company_id``. Транзакционный пулер отдаёт одно
серверное соединение разным клиентам, и настройка одной компании может «протечь» в запрос
другой - это утечка данных между арендаторами. Поэтому такие URL запрещены.
Модуль не зависит от настроек Django (импортируется и тестируется отдельно).
"""

from urllib.parse import parse_qs, urlsplit

from django.core.exceptions import ImproperlyConfigured

_DENIED_PORTS = {
    6543: "транзакционный пулер (Supabase, порт 6543)",
    6432: "порт 6432 - стандартный порт PgBouncer",
}
# dj_database_url передаёт неизвестные ключи query в OPTIONS, и host/hostaddr переопределили бы
# хост из URL (в обход проверки хоста).
_DENIED_QUERY_KEYS = {"host", "hostaddr"}


class UnparsableDatabaseUrl(ValueError):
    """URL нельзя однозначно разобрать (текст исключения не содержит URL)."""


def _parse(url):
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port
        query = parse_qs(parts.query, keep_blank_values=True)
    except ValueError:
        raise UnparsableDatabaseUrl from None
    if "," in parts.netloc.rpartition("@")[2] or not host:
        raise UnparsableDatabaseUrl
    return host.lower(), port, query


def pooler_problem(url):
    """Описание проблемы (без пароля) или None. Эвристика: распознаются хосты Neon с «-pooler.»,
    порты 6543/6432, pgbouncer=true и ключи host/hostaddr; другие пулеры НЕ распознаются.
    Неразбираемый URL: UnparsableDatabaseUrl."""
    if not url:
        return None
    host, port, query = _parse(url)
    if "-pooler." in host:
        return f"хост {host!r} - пулер Neon (-pooler)"
    if port in _DENIED_PORTS:
        return _DENIED_PORTS[port]
    if _DENIED_QUERY_KEYS & {k.lower() for k in query}:
        return "параметры host/hostaddr в DATABASE_URL переопределяют хост"
    values = [v for k, vs in query.items() if k.lower() == "pgbouncer" for v in vs]
    if any(v.strip().lower() in ("true", "1", "yes", "on") for v in values):
        return "параметр pgbouncer=true в DATABASE_URL"
    return None


def check_database_url(url, *, serverless, debug, pooler_ok):
    """ImproperlyConfigured, если URL - транзакционный пулер, а режим этого не допускает.

    serverless: проверка всегда, DATABASE_POOLER_OK её не отключает;
    иначе в продакшене (debug=False) - пока не задано DATABASE_POOLER_OK=true.
    Проверка консервативна (fail closed): URL, который нельзя разобрать, тоже отклоняется.
    """
    if not (serverless or (not debug and not pooler_ok)):
        return
    try:
        problem = pooler_problem(url)
    except UnparsableDatabaseUrl:
        raise ImproperlyConfigured(
            "Не удалось разобрать DATABASE_URL (несколько хостов, неверный порт или формат). "
            "Пока включена защита от пулеров, нужна обычная строка вида "
            "postgresql://роль:пароль@хост:порт/база. Значение в сообщение не включено."
        ) from None
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
