"""Нестрогий поиск по спискам: слова ищутся по частям, регистр и пробелы в номерах не важны.

Запрос разбивается на слова; запись подходит, если КАЖДОЕ слово встречается (как часть строки)
хотя бы в одном из полей. Для номеров машин пробелы и дефисы убираются с обеих сторон, поэтому
«887», «887 hhh», «887-HHH-15» находят «887HHH15».
"""

import re

from django.db.models import F, Q, Value
from django.db.models.functions import Replace, Upper

MAX_TERMS = 6


def compact(term: str) -> str:
    """Слово без пробелов и дефисов, в верхнем регистре (для сравнения номеров)."""
    return re.sub(r"[\s\-]+", "", term).upper()


def norm_expr(field: str):
    """SQL-выражение: значение поля без пробелов и дефисов, в верхнем регистре."""
    return Replace(Replace(Upper(F(field)), Value(" "), Value("")), Value("-"), Value(""))


def split_terms(text: str) -> list[str]:
    return [t for t in text.split() if t][:MAX_TERMS]


def plate_q(prefix: str, term: str) -> Q:
    """Условие «номер машины содержит слово» для набора псевдонимов (см. add_plate_aliases)."""
    c = compact(term)
    return Q(**{f"{prefix}__icontains": c}) if c else Q()


def search(qs, text: str, *, fields=(), plates=(), extra=None):
    """Фильтр queryset по тексту. fields - обычные текстовые поля (icontains), plates - поля с
    номерами (сравнение без пробелов и дефисов), extra(term) - дополнительное Q/Exists на слово."""
    terms = split_terms(text or "")
    if not terms:
        return qs
    aliases = {f"_plate_{i}": norm_expr(f) for i, f in enumerate(plates)}
    if aliases:
        qs = qs.alias(**aliases)
    for term in terms:
        cond = Q()
        for f in fields:
            cond |= Q(**{f"{f}__icontains": term})
        for name in aliases:
            cond |= plate_q(name, term)
        if extra is not None:
            cond |= extra(term)
        qs = qs.filter(cond)
    return qs
