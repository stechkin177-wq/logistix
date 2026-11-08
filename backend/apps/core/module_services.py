"""Конфигурация модулей компании: CompanyModule и проекция Company.modules.

``CompanyModule`` - источник правды (права доступа читаются из него). ``Company.modules`` -
временная проекция (список включённых не-core модулей в порядке создания строк),
обновляется в ТОЙ ЖЕ транзакции, что и CompanyModule. ``core`` не хранится: он включён всегда.
Правила включения и отключения (тариф, зависимости, защита finance) - в этом же модуле ниже
(enable_module / disable_module); здесь низкоуровневая запись и чтение.
"""

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException

from apps.billing.services import get_subscription

from . import module_catalog
from .audit import services as audit
from .models import Company, CompanyModule, Module
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


# --- правила включения и отключения (A4) ----------------------------------------------------------


class ModuleConfigError(APIException):
    """Нарушение правил конфигурации модулей: {"detail", "code", "modules": [...]}.

    Коды: module_unknown, module_core, module_retired (400); module_not_in_plan, module_requires,
    module_has_dependents, module_protected (409).
    """

    status_code = 409

    def __init__(self, code: str, detail: str, modules=None, status_code: int | None = None):
        body = {"detail": detail, "code": code}
        if modules is not None:
            body["modules"] = list(modules)
        super().__init__(detail=body, code=code)
        if status_code is not None:
            self.status_code = status_code


# Защита отключения: код модуля -> проверки f(company) -> текст причины или None. Приложения
# регистрируют их при запуске (ядро не импортирует модели других приложений).
_DISABLE_GUARDS: dict[str, list] = {}


def register_disable_guard(module_code: str, guard) -> None:
    guards = _DISABLE_GUARDS.setdefault(module_code, [])
    if guard not in guards:
        guards.append(guard)


def _catalog() -> dict[str, Module]:
    return {m.code: m for m in Module.objects.all()}


def _plan_modules(company_id: int) -> set[str]:
    sub = get_subscription(company_id)
    return set(sub.plan.modules or []) if sub is not None else set()


def _dependents(catalog, code: str, enabled: set[str]) -> list[str]:
    """Включённые модули, жёстко зависящие от code (прямые)."""
    return [c for c in enabled if c != code and code in (catalog[c].requires or [])]


def _names(catalog, codes) -> str:
    return ", ".join(f"«{catalog[c].name}»" if c in catalog else c for c in codes)


def enable_problem(company_id, catalog, enabled: set[str], plan: set[str], code: str):
    """Почему модуль нельзя включить: (code, текст, модули, http-статус) или None."""
    module = catalog.get(code)
    if module is None:
        return ("module_unknown", f"Неизвестный модуль: {code}", None, 400)
    if module.is_core:
        return ("module_core", "Основа всегда включена и не настраивается", None, 400)
    if module.status == Module.RETIRED:
        return ("module_retired", f"Модуль «{module.name}» выведен из каталога", None, 400)
    if code not in plan:
        return (
            "module_not_in_plan",
            f"Модуль «{module.name}» недоступен на вашем тарифе",
            None,
            409,
        )
    missing = [r for r in module.requires if r in catalog and not catalog[r].is_core]
    missing = [r for r in missing if r not in enabled]
    if missing:
        return (
            "module_requires",
            f"Сначала включите: {_names(catalog, missing)}",
            missing,
            409,
        )
    return None


def _disable_plan(company: Company, catalog, enabled: set[str], code: str, cascade: bool):
    """Список модулей к отключению (сначала зависимые) либо ModuleConfigError."""
    module = catalog.get(code)
    if module is None:
        raise ModuleConfigError("module_unknown", f"Неизвестный модуль: {code}", status_code=400)
    if module.is_core:
        raise ModuleConfigError(
            "module_core", "Основа всегда включена и не отключается", status_code=400
        )
    if code not in enabled:
        return []
    order: list[str] = []

    def visit(current: str):
        for dep in _dependents(catalog, current, enabled):
            if dep not in order:
                visit(dep)
        if current not in order:
            order.append(current)

    direct = _dependents(catalog, code, enabled)
    if direct and not cascade:
        raise ModuleConfigError(
            "module_has_dependents",
            f"Нельзя отключить «{module.name}»: от него зависят {_names(catalog, direct)}. "
            "Сначала отключите их или подтвердите отключение вместе с ними.",
            direct,
        )
    visit(code)
    for target in order:  # защита проверяется для каждого отключаемого модуля, до любых изменений
        for guard in _DISABLE_GUARDS.get(target, []):
            reason = guard(company)
            if reason:
                raise ModuleConfigError("module_protected", reason, [target])
    return order


def disable_problem(company: Company, catalog, enabled: set[str], code: str):
    """Почему модуль нельзя отключить (без каскада): (code, текст, модули) или None."""
    try:
        _disable_plan(company, catalog, enabled, code, cascade=False)
    except ModuleConfigError as exc:
        return (exc.detail["code"], str(exc.detail["detail"]), exc.detail.get("modules"))
    return None


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
def enable_module(company: Company, code: str, user=None, reason: str = "") -> list[str]:
    """Включить модуль: есть в каталоге, не core, доступен по тарифу, все requires включены.

    Данные модуля не создаются и не меняются: при повторном включении всё снова доступно.
    Повторное включение уже включённого - без изменений. Возвращает Company.modules.
    """
    locked = Company.objects.select_for_update().get(pk=company.pk)
    with tenant_context(locked.pk):
        catalog = _catalog()
        enabled = set(enabled_module_codes(locked.pk))
        if code in enabled:
            company.modules = list(locked.modules)
            return company.modules
        problem = enable_problem(locked.pk, catalog, enabled, _plan_modules(locked.pk), code)
        if problem:
            raise ModuleConfigError(problem[0], problem[1], problem[2], status_code=problem[3])
        _write(locked, code, True, user, reason, timezone.now())
        codes = sync_projection(locked)
    company.modules = codes
    return codes


@transaction.atomic
def disable_module(
    company: Company, code: str, user=None, reason: str = "", cascade: bool = False
) -> list[str]:
    """Отключить модуль.

    Запрещено при включённых зависимых (module_has_dependents со списком); cascade=True явно
    отключает и зависимых (транзакционно, все или ни одного). Модули под защитой (finance при
    engine shadow/new) не отключаются никак (module_protected). Данные модулей НЕ удаляются.
    """
    locked = Company.objects.select_for_update().get(pk=company.pk)
    with tenant_context(locked.pk):
        catalog = _catalog()
        enabled = set(enabled_module_codes(locked.pk))
        targets = _disable_plan(locked, catalog, enabled, code, cascade)
        now = timezone.now()
        for target in targets:
            suffix = "" if target == code else f" (каскадно вместе с «{catalog[code].name}»)"
            _write(locked, target, False, user, f"{reason}{suffix}".strip(), now)
        codes = sync_projection(locked)
    company.modules = codes
    return codes


def describe_modules(company: Company, plan_modules=None) -> list[dict]:
    """Каталог + состояние компании + доступность по тарифу + зависимости + причины отказа."""
    with tenant_context(company.pk):
        catalog = _catalog()
        enabled = set(enabled_module_codes(company.pk))
        plan = set(plan_modules) if plan_modules is not None else _plan_modules(company.pk)
        result = []
        for module in sorted(catalog.values(), key=lambda m: (m.sort, m.id)):
            code = module.code
            is_on = module.is_core or code in enabled
            in_plan = module.is_core or code in plan
            dependents = [] if module.is_core else _dependents(catalog, code, enabled)
            can_enable = can_disable = False
            blocker = None
            if not module.is_core:
                if not is_on:
                    problem = enable_problem(company.pk, catalog, enabled, plan, code)
                    can_enable = problem is None
                    if problem:
                        blocker = {"code": problem[0], "detail": problem[1], "modules": problem[2]}
                else:
                    problem = disable_problem(company, catalog, enabled, code)
                    can_disable = problem is None
                    if problem:
                        blocker = {"code": problem[0], "detail": problem[1], "modules": problem[2]}
            result.append(
                {
                    "code": code,
                    "name": module.name,
                    "description": module.description,
                    "status": module.status,
                    "is_core": module.is_core,
                    "enabled": is_on,
                    "available_in_plan": in_plan,
                    "effective": is_on and in_plan,
                    "requires": list(module.requires),
                    "enhances": list(module.enhances),
                    "dependents": dependents,
                    "can_enable": can_enable,
                    "can_disable": can_disable,
                    "blocker": blocker,
                }
            )
        return result


# --- профили деятельности (A6) --------------------------------------------------------------------


def _requires_order(catalog, codes) -> list[str]:
    """Коды в порядке, при котором requires идут раньше зависимых (устойчиво к порядку профиля)."""
    ordered: list[str] = []

    def visit(code):
        if code in ordered or code not in catalog:
            return
        for dep in catalog[code].requires:
            if dep in codes:
                visit(dep)
        ordered.append(code)

    for code in codes:
        visit(code)
    return ordered


@transaction.atomic
def apply_profile(company: Company, profile, user=None, reason: str = "", replace: bool = False):
    """Применить профиль деятельности: включить его модули, недоступные пропустить и сообщить.

    Без replace остальные включённые модули не трогаются. С replace=True отключаются модули,
    которых нет в применяемом наборе (зависимости и защита finance проверяются как обычно,
    при отказе откатывается всё). Возвращает {"enabled", "disabled", "skipped": [{code, error_code,
    detail}]}.
    """
    locked = Company.objects.select_for_update().get(pk=company.pk)
    note = f"Профиль «{profile.name}»" + (f": {reason}" if reason else "")
    enabled_now: list[str] = []
    disabled_now: list[str] = []
    skipped: list[dict] = []
    with tenant_context(locked.pk):
        catalog = _catalog()
        enabled = set(enabled_module_codes(locked.pk))
        plan = _plan_modules(locked.pk)
        wanted = [c for c in profile.modules if c in catalog and not catalog[c].is_core]
        target: list[str] = []
        have = set(enabled)
        for code in _requires_order(catalog, wanted):
            if code in enabled:
                target.append(code)
                continue
            problem = enable_problem(locked.pk, catalog, have, plan, code)
            if problem:
                skipped.append({"code": code, "error_code": problem[0], "detail": problem[1]})
                continue
            _write(locked, code, True, user, note, timezone.now())
            have.add(code)
            enabled_now.append(code)
            target.append(code)
        unknown = [c for c in profile.modules if c not in catalog]
        for code in unknown:
            skipped.append(
                {
                    "code": code,
                    "error_code": "module_unknown",
                    "detail": f"Неизвестный модуль: {code}",
                }
            )
        if replace:
            leftover = [c for c in enabled_module_codes(locked.pk) if c not in set(target)]
            for code in leftover:
                if code not in set(enabled_module_codes(locked.pk)):
                    continue  # уже отключён каскадом
                current = set(enabled_module_codes(locked.pk))
                for victim in _disable_plan(locked, catalog, current, code, cascade=True):
                    _write(locked, victim, False, user, note, timezone.now())
                    disabled_now.append(victim)
        codes = sync_projection(locked)
    company.modules = codes
    return {"enabled": enabled_now, "disabled": disabled_now, "skipped": skipped}
