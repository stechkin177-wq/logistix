"""Защита модуля finance от отключения (конфигурация модулей компании, A4).

Модуль finance нельзя отключить, пока у компании engine - shadow или new: фоновые финансовые
хуки (признание дохода, синхронизация расхода) работают независимо от видимости раздела, а
отключённый API оставил бы пользователей без доступа к уже ведущемуся учёту.
"""

from .engine import company_engine

PROTECTED_ENGINES = ("shadow", "new")


def finance_disable_guard(company) -> str | None:
    engine = company_engine(company.pk)
    if engine in PROTECTED_ENGINES:
        return (
            "Модуль «Финансы» нельзя отключить: у компании включён новый финансовый учёт "
            f"(режим {engine}). Данные и расчёты продолжают вестись."
        )
    return None
