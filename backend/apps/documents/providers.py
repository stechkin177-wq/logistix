"""Реестр поставщиков документов (addendum v1.1, разд. 2.3).

Ядро documents не знает моделей других модулей: каждый модуль-поставщик регистрирует объект
DocumentProvider, который сообщает, какие виды документов и по каким субъектам он поставляет,
как загрузить субъект, как построить контекст подстановки и какое право нужно для выдачи.
Вид доступен компании, только если модуль поставщика включён у компании (и есть в тарифе)
и у пользователя есть право. Встроенные виды (договор, заявка, договор-заявка перевозчику, акт,
счёт на оплату, CMR, письмо) регистрируются встроенными поставщиками (documents/builtin.py).

Файл не импортирует модели других приложений.
"""

from __future__ import annotations

from collections.abc import Iterable


class DocumentProvider:
    """Интерфейс поставщика документов модуля.

    module_code    - код модуля каталога, которому принадлежит поставщик;
    subject_types  - субъекты вида "<модуль>.<сущность>" (например, drivers.driver);
    kinds          - виды документов (должны входить в documents.models.KINDS);
    build_context  - блоки подстановки поставщика (ядро добавляет блоки doc и company);
    required_permission - право на выдачу вида по субъекту (None - только documents.create);
    load_subject   - загрузка субъекта по id в контексте компании (None - не найден).
    """

    module_code: str = ""
    subject_types: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ()

    def build_context(self, kind: str, subject, language: str) -> dict:
        raise NotImplementedError

    def required_permission(self, kind: str) -> str | None:
        return None

    def load_subject(self, subject_type: str, subject_id: int):
        raise NotImplementedError


_PROVIDERS: list[DocumentProvider] = []


def _validate(provider: DocumentProvider) -> None:
    from .models import KINDS

    if not provider.module_code:
        raise ValueError("У поставщика документов не задан module_code")
    if not provider.subject_types or not provider.kinds:
        raise ValueError("У поставщика документов нужны subject_types и kinds")
    unknown = sorted(set(provider.kinds) - set(KINDS))
    if unknown:
        raise ValueError(
            f"Неизвестные виды документов у поставщика {provider.module_code}: {', '.join(unknown)}"
        )


def register_provider(provider: DocumentProvider) -> DocumentProvider:
    """Зарегистрировать поставщика (идемпотентно по объекту)."""
    _validate(provider)
    if provider not in _PROVIDERS:
        _PROVIDERS.append(provider)
    return provider


def unregister_provider(provider: DocumentProvider) -> None:
    if provider in _PROVIDERS:
        _PROVIDERS.remove(provider)


def all_providers() -> list[DocumentProvider]:
    return list(_PROVIDERS)


def find_provider(kind: str, subject_type: str) -> DocumentProvider | None:
    for provider in _PROVIDERS:
        if kind in provider.kinds and subject_type in provider.subject_types:
            return provider
    return None


def providers_for_kind(kind: str) -> list[DocumentProvider]:
    return [p for p in _PROVIDERS if kind in p.kinds]


def available_kinds(effective_modules: Iterable[str]) -> list[str]:
    """Виды документов, доступные при данном наборе эффективных модулей (порядок стабильный)."""
    modules = set(effective_modules)
    result: list[str] = []
    for provider in _PROVIDERS:
        if provider.module_code in modules:
            result.extend(k for k in provider.kinds if k not in result)
    return result
