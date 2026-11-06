"""Сигналы ядра. Подписчики других приложений сидят данные новой компании."""

from django.dispatch import Signal

# Отправляется create_company_with_defaults после всех сидингов; аргумент: company.
# Вне контекста компании: подписчик сам открывает tenant_context(company.id).
company_created = Signal()
