"""Конфигурация модулей компании: CompanyModule и проекция Company.modules.

``CompanyModule`` - источник правды (права доступа читаются из него). ``Company.modules`` -
временная проекция (список включённых не-core модулей в порядке создания строк),
обновляется в ТОЙ ЖЕ транзакции, что и CompanyModule. ``core`` не хранится: он включён всегда.
Здесь низкоуровневая запись и чтение; правила включения и отключения - ниже в этом модуле.
"""

from django.db import transaction
from django.utils import timezone

from . import module_catalog
from .audit import services as audit
from .models import Company, CompanyModule
from .tenancy import tenant_context

# Модули, которые можно включать компании: не-core модули каталога.
VALID_MODULES = module_catalog.non_core_codes()
# При создании компании с forwarding вместе с ним включаются finance и documents (они были частью
# forwarding до разделения модулей; поведение компаний не меняется).
FORWARDING_COMPANIONS = ("finance", "documents")


def with_default_companions(codes: list[str]) -> list[str]:
    """Набор для новой компании: forwarding тянет finance и documents (порядок сохраняется)."""
    result = list(dict.fromkeys(codes))
    if "forwarding" in result:
        result += [c for c in FORWARDING_COMPANIONS if c not in result]
    return result


def unmet_requirements(codes) -> list[str]:
    """Невыполненные жёсткие зависимости набора по код-реестру: ["finance -> forwarding"]."""
    have = set(codes) | {module_catalog.CORE}
    by_code = {m["code"]: m for m in module_catalog.MODULES}
    problems = []
    for code in codes:
        for dep in by_code[code]["requires"]:
            if dep not in have:
                problems.append(f"{code} -> {dep}")
    return problems


def enabled_module_codes(company_id: int) -> list[str]:
    """Включённые модули компании из CompanyModule (без core), в порядке создания строк."""
    with tenant_context(company_id):
        return list(
            CompanyModule.objects.filter(enabled=True)
            .order_by("id")
            .values_list("module_code", flat=True)
        )


def effective_module_codes(company_id: int, plan_modules) -> list[str]:
    """Эффективный доступ: модуль есть в тарифе И включён в CompanyModule."""
    allowed = set(plan_modules or [])
    return [m for m in enabled_module_codes(company_id) if m in allowed]


def sync_projection(company: Company) -> list[str]:
    """Company.modules := включённые модули из CompanyModule (в одной транзакции с изменением)."""
    codes = enabled_module_codes(company.pk)
    if list(company.modules or []) != codes:
        Company.objects.filter(pk=company.pk).update(modules=codes)
    company.modules = codes
    return codes


def _write(company, code, enabled, user, reason, now, audit_log=True):
    """Включает/отключает одну строку CompanyModule (создаёт при первом включении) + аудит."""
    actor = user if getattr(user, "pk", None) else None
    row = CompanyModule.objects.filter(module_code=code).first()
    if enabled:
        if row is None:
            row = CompanyModule.objects.create(
                module_code=code, enabled=True, enabled_at=now, enabled_by=actor, reason=reason
            )
            old = None
        else:
            old = row.enabled
            row.enabled = True
            row.enabled_at, row.enabled_by, row.reason = now, actor, reason
            row.save(update_fields=["enabled", "enabled_at", "enabled_by", "reason"])
    else:
        old = row.enabled
        row.enabled = False
        row.disabled_at, row.disabled_by, row.reason = now, actor, reason
        row.save(update_fields=["enabled", "disabled_at", "disabled_by", "reason"])
    if audit_log:
        audit.log(
            "create" if old is None else "update",
            row,
            user,
            {"module_code": code, "enabled": [old, enabled], "reason": reason},
        )
    return row


@transaction.atomic
def set_company_modules(
    company: Company,
    modules,
    *,
    user=None,
    reason: str = "",
    audit_changes: bool = True,
) -> list[str]:
    """Установить ТОЧНЫЙ набор включённых не-core модулей компании.

    Строки CompanyModule создаются при первом включении, при отключении остаются с enabled=False
    (данные модулей не удаляются). Проверка зависимостей и тарифа - в enable_module/disable_module;
    здесь только запись и синхронизация проекции. Возвращает итоговый список (Company.modules).
    """
    wanted = list(dict.fromkeys(modules))
    unknown = sorted(set(wanted) - VALID_MODULES)
    if unknown:
        raise ValueError(f"Неизвестные модули: {', '.join(unknown)}")
    now = timezone.now()
    locked = Company.objects.select_for_update().get(pk=company.pk)
    with tenant_context(locked.pk):
        rows = {r.module_code: r for r in CompanyModule.objects.select_for_update()}
        for code in wanted:  # в порядке перечисления: порядок строк = порядок модулей
            row = rows.get(code)
            if row is None or not row.enabled:
                _write(locked, code, True, user, reason, now, audit_log=audit_changes)
        for code, row in rows.items():
            if code not in wanted and row.enabled:
                _write(locked, code, False, user, reason, now, audit_log=audit_changes)
        codes = sync_projection(locked)
    company.modules = codes
    return codes
