"""Поставщик документов модуля drivers для универсальной системы документов (documents).

Своих механизмов хранения и шаблонов нет: используется общий вид «письмо/справка» (letter), а
содержимое подставляется из карточки водителя. Субъект: ``drivers.driver``. Выдача требует модуль
drivers (включён и в тарифе) и право drivers.view; журнал, номер, снимок и скачивание - общие.
"""

from apps.documents.providers import DocumentProvider

from .models import Driver


class DriversDocumentProvider(DocumentProvider):
    module_code = "drivers"
    subject_types = ("drivers.driver",)
    kinds = ("letter",)

    def required_permission(self, kind):
        return "drivers.view"

    def load_subject(self, subject_type, subject_id):
        return Driver.objects.filter(pk=subject_id).first()  # компания и мягкое удаление - менеджер

    def build_context(self, kind, subject, language):
        parts = [f"Водитель: {subject.full_name}"]
        if subject.license_number:
            cats = f", категории {subject.license_categories}" if subject.license_categories else ""
            parts.append(f"Водительское удостоверение {subject.license_number}{cats}")
        if subject.license_expires:
            parts.append(f"Действует до {subject.license_expires:%d.%m.%Y}")
        return {
            "letter": {
                "recipient": subject.full_name,
                "subject": "Справка о водителе",
                "body": "\n".join(parts),
            }
        }


DRIVERS_PROVIDER = DriversDocumentProvider()
