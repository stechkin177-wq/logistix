import ipaddress
from copy import deepcopy

from django.conf import settings

from apps.core.tenancy import NoTenantContext, get_current_company_id

ACTIONS = ("create", "update", "delete", "restore", "login")
SENSITIVE_FIELDS = {"password", "token", "refresh", "access", "secret"}
MASK = "***"
_SKIP_SNAPSHOT = {"id", "company_id"}


def _mask(changes: dict) -> dict:
    """Копия changes: значения чувствительных ключей -> "***" (и на 1 уровень глубже)."""
    out = {}
    for key, value in changes.items():
        if str(key).lower() in SENSITIVE_FIELDS:
            out[key] = MASK
        elif isinstance(value, dict):
            out[key] = {
                k: (MASK if str(k).lower() in SENSITIVE_FIELDS else deepcopy(v))
                for k, v in value.items()
            }
        else:
            out[key] = deepcopy(value)
    return out


def diff(before: dict, after: dict) -> dict:
    """{поле: [было, стало]} только для изменившихся полей (отсутствующее = None)."""
    changed = {}
    for key in {*before, *after}:
        old, new = before.get(key), after.get(key)
        if old != new:
            changed[key] = [old, new]
    return dict(sorted(changed.items()))


def snapshot(obj) -> dict:
    """Значения конкретных полей модели ({attname: значение}) без id и company_id."""
    return {
        f.attname: getattr(obj, f.attname)
        for f in obj._meta.concrete_fields
        if f.attname not in _SKIP_SNAPSHOT
    }


def log(action, obj, user, changes=None, *, object_type=None, object_id=None, ip=None):
    """Пишет запись аудита и возвращает её.

    Компания берётся из контекста компании (fail closed) либо, при его отсутствии, из
    obj.company_id. Значения чувствительных полей в changes заменяются на "***".
    """
    from .models import AuditLog

    if action not in ACTIONS:
        raise ValueError(f"Неизвестное действие аудита: {action!r}")
    company_id = get_current_company_id()
    if company_id is None:
        company_id = getattr(obj, "company_id", None)
    if company_id is None:
        raise NoTenantContext("Нет компании для записи аудита")
    if obj is not None:
        object_type = object_type or obj._meta.label_lower
        object_id = obj.pk if object_id is None else object_id
        object_repr = str(obj)[:255]
    else:
        object_repr = ""
    if not object_type or object_id is None:
        raise ValueError("Нужны obj либо object_type и object_id")
    row = AuditLog(
        company_id=company_id,
        user=user if user is not None and getattr(user, "pk", None) else None,
        action=action,
        object_type=object_type,
        object_id=str(object_id),
        object_repr=object_repr,
        changes=_mask(changes or {}),
        ip=ip,
    )
    row.save()
    return row


def client_ip(request) -> str | None:
    """IP клиента: первый адрес X-Forwarded-For при TRUST_PROXY_HEADERS, иначе REMOTE_ADDR."""
    meta = request.META
    candidates = []
    if getattr(settings, "TRUST_PROXY_HEADERS", False):
        forwarded = meta.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            candidates.append(forwarded.split(",")[0].strip())
    candidates.append((meta.get("REMOTE_ADDR") or "").strip())
    for value in candidates:
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            continue
    return None


def log_login(request, user, company_id, changes=None):
    """Запись `login` в контексте компании токена (контекст после выхода сбрасывается)."""
    from apps.core.tenancy import tenant_context

    with tenant_context(company_id):
        return log("login", user, user, changes, ip=client_ip(request))
