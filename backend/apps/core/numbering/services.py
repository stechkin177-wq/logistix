"""Нумерация документов по шаблонам.

Шаблон: литералы и плейсхолдеры {year}, {index}, {order}, {n}.
- {year} - текущий год в часовом поясе компании (Company.timezone);
- {index} - значение счётчика, с ведущими нулями до `digits` (0 - без нулей);
- {order}, {n} - из контекста (номер заявки и порядковый номер рейса в ней).

Счётчики сквозные: при смене года счётчик НЕ сбрасывается. Владелец может сам задать
next_value (в том числе уменьшить); уникальность номеров обеспечивают потребляющие модели.
"""

import string
from datetime import datetime
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from apps.core.models import Company
from apps.core.tenancy import NoTenantContext, get_current_company_id, tenant_context

from .models import NumberingRule

CONTEXT_PLACEHOLDERS = frozenset({"order", "n"})
BASE_PLACEHOLDERS = frozenset({"year", "index"})
MAX_DIGITS = 10

KINDS: dict[str, dict] = {
    "order": {
        "name": "Заявки",
        "description": "Номер заявки клиента",
        "required": {"index"},
        "allowed": BASE_PLACEHOLDERS,
    },
    "trip": {
        "name": "Рейсы",
        "description": "Номер рейса внутри заявки: номер заявки и порядковый номер рейса",
        "required": {"order", "n"},
        "allowed": BASE_PLACEHOLDERS | CONTEXT_PLACEHOLDERS,
    },
    "consolidated_trip": {
        "name": "Сборные рейсы",
        "description": "Номер сборного рейса",
        "required": {"index"},
        "allowed": BASE_PLACEHOLDERS,
    },
    "invoice_out": {
        "name": "Счета клиентам",
        "description": "Номер счёта, выставляемого клиенту",
        "required": {"index"},
        "allowed": BASE_PLACEHOLDERS,
    },
    "invoice_in": {
        "name": "Счета от перевозчиков",
        "description": "Номер счёта, полученного от перевозчика",
        "required": {"index"},
        "allowed": BASE_PLACEHOLDERS,
    },
}

DEFAULTS: dict[str, dict] = {
    "order": {"template": "ORD-{year}-{index}", "digits": 5},
    "trip": {"template": "{order}-{n}", "digits": 5},
    "consolidated_trip": {"template": "C{index}", "digits": 0},
    "invoice_out": {"template": "СЧ-{year}-{index}", "digits": 5},
    "invoice_in": {"template": "ПС-{year}-{index}", "digits": 5},
}


def _parse(template: str) -> list[tuple[str, str | None]]:
    """[(литерал, имя плейсхолдера | None)]. ValueError на любом нарушении синтаксиса."""
    try:
        parts = list(string.Formatter().parse(template))
    except ValueError as exc:
        raise ValueError("Несбалансированные фигурные скобки") from exc
    result = []
    for literal, field, spec, conv in parts:
        if "{" in literal or "}" in literal:
            raise ValueError("Несбалансированные фигурные скобки")
        if field is not None and (spec or conv or not field.isidentifier()):
            raise ValueError(f"Недопустимый плейсхолдер {{{field}}}")
        result.append((literal, field))
    return result


def validate_template(kind: str, template: str) -> list[str]:
    """Проверяет шаблон для вида; возвращает список ошибок (пустой - шаблон верен)."""
    spec = KINDS[kind]
    try:
        parsed = _parse(template)
    except ValueError as exc:
        return [str(exc)]
    used = {field for _, field in parsed if field is not None}
    errors = []
    unknown = sorted(used - spec["allowed"])
    if unknown:
        allowed = ", ".join(f"{{{p}}}" for p in sorted(spec["allowed"]))
        errors.append(
            f"Недопустимые плейсхолдеры: {', '.join(f'{{{p}}}' for p in unknown)}. "
            f"Допустимы: {allowed}"
        )
    missing = sorted(spec["required"] - used)
    if missing:
        errors.append(f"Шаблон должен содержать: {', '.join(f'{{{p}}}' for p in missing)}")
    return errors


def _company_year(tz_name: str) -> int:
    """Текущий год в часовом поясе компании."""
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001 - неизвестная зона не должна ронять нумерацию
        tz = ZoneInfo("Asia/Almaty")
    now: datetime = timezone.now()
    return now.astimezone(tz).year


def _render(rule: NumberingRule, tz_name: str, context: dict) -> str:
    out = []
    for literal, field in _parse(rule.template):
        out.append(literal)
        if field is None:
            continue
        if field == "year":
            out.append(str(_company_year(tz_name)))
        elif field == "index":
            out.append(
                f"{rule.next_value:0{rule.digits}d}" if rule.digits else str(rule.next_value)
            )
        elif field in context:
            out.append(str(context[field]))
        else:
            raise ValueError(f"Не передан обязательный параметр шаблона: {field}")
    return "".join(out)


def _current_company() -> Company:
    company_id = get_current_company_id()
    if company_id is None:
        raise NoTenantContext("Нет текущей компании для нумерации")
    return Company.objects.get(pk=company_id)


def next_number(kind: str, **context: str | int) -> str:
    """Выдаёт следующий номер для текущей компании и увеличивает счётчик (если в шаблоне
    есть {index}). Строка правила блокируется на время транзакции, поэтому параллельные
    вызовы получают разные последовательные номера. Откат внешней транзакции откатывает
    и счётчик (пропусков не возникает)."""
    if kind not in KINDS:
        raise ValueError(f"Неизвестный вид нумерации: {kind!r}")
    company = _current_company()
    with transaction.atomic():
        rule = _locked_rule(company, kind)
        number = _render(rule, company.timezone, context)
        if "{index}" in rule.template:
            rule.next_value += 1
            rule.save(update_fields=["next_value"])
        return number


def _locked_rule(company: Company, kind: str) -> NumberingRule:
    qs = NumberingRule.objects.select_for_update()
    rule = qs.filter(kind=kind).first()
    if rule is None:  # компания без сидинга: создаём правило по умолчанию
        NumberingRule.all_objects.get_or_create(company=company, kind=kind, defaults=DEFAULTS[kind])
        rule = qs.get(kind=kind)
    return rule


def peek_number(kind: str, **context: str | int) -> str:
    """Пример следующего номера без изменения счётчика."""
    company = _current_company()
    rule = NumberingRule.objects.filter(kind=kind).first() or NumberingRule(
        company=company, kind=kind, next_value=1, **DEFAULTS[kind]
    )
    return _render(rule, company.timezone, context)


def sample_numbers() -> dict[str, str]:
    """Примеры для всех видов; пример рейса строится на примере номера заявки и n=1."""
    samples = {kind: peek_number(kind) for kind in KINDS if kind != "trip"}
    samples["trip"] = peek_number("trip", order=samples["order"], n=1)
    return samples


@transaction.atomic
def seed_numbering(company: Company) -> None:
    """Создаёт правила по умолчанию. Идемпотентно: существующие правила не меняются."""
    with tenant_context(company.id):  # RLS: WITH CHECK по app.company_id
        for kind, spec in DEFAULTS.items():
            NumberingRule.all_objects.get_or_create(company=company, kind=kind, defaults=spec)
