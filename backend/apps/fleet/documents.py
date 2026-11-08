"""Поставщик документов модуля fleet для универсальной системы документов (documents).

Своих механизмов хранения и шаблонов нет: используется общий вид «письмо/справка» (letter).
Субъекты: ``fleet.vehicle`` (справка по технике), ``fleet.insurance`` (по страховке),
``fleet.servicerecord`` (акт/справка об обслуживании). Денежных сумм в документах fleet нет:
стоимость живёт в Finance G1. Выдача требует модуль fleet и право fleet.view.
"""

from apps.documents.providers import DocumentProvider

from .models import Insurance, ServiceRecord, Vehicle


def _date(value):
    return f"{value:%d.%m.%Y}" if value else "-"


def _vehicle_lines(v: Vehicle) -> list[str]:
    lines = [f"{v.get_kind_display()} {v.plate}"]
    desc = " ".join(x for x in (v.make, v.model) if x)
    if desc:
        lines.append(f"Марка и модель: {desc}" + (f", {v.year} г." if v.year else ""))
    if v.vin:
        lines.append(f"VIN: {v.vin}")
    return lines


class FleetDocumentProvider(DocumentProvider):
    module_code = "fleet"
    subject_types = ("fleet.vehicle", "fleet.insurance", "fleet.servicerecord")
    kinds = ("letter",)

    def required_permission(self, kind):
        return "fleet.view"

    def load_subject(self, subject_type, subject_id):
        model = {
            "fleet.vehicle": Vehicle,
            "fleet.insurance": Insurance,
            "fleet.servicerecord": ServiceRecord,
        }[subject_type]
        obj = model.objects.filter(pk=subject_id).first()
        if obj is not None and subject_type != "fleet.vehicle":
            if Vehicle.objects.filter(pk=obj.vehicle_id).first() is None:  # техника удалена
                return None
        return obj

    def build_context(self, kind, subject, language):
        if isinstance(subject, Vehicle):
            title, lines = "Справка по технике", _vehicle_lines(subject)
        elif isinstance(subject, Insurance):
            title = "Справка о страховании"
            lines = [
                *_vehicle_lines(subject.vehicle),
                f"{subject.get_kind_display()}, полис {subject.policy_number or '-'}",
                f"Страховщик: {subject.insurer or '-'}",
                f"Срок: {_date(subject.starts_at)} - {_date(subject.expires_at)}",
            ]
        else:
            title = "Акт об обслуживании техники"
            lines = [
                *_vehicle_lines(subject.vehicle),
                f"{subject.get_kind_display()}: {subject.title}",
                f"Дата выполнения: {_date(subject.done_date)}",
            ]
            if subject.odometer_km is not None:
                lines.append(f"Пробег: {subject.odometer_km} км")
            if subject.description:
                lines.append(f"Выполненные работы: {subject.description}")
        return {
            "letter": {
                "recipient": getattr(subject, "plate", None) or subject.vehicle.plate,
                "subject": title,
                "body": "\n".join(lines),
            }
        }


FLEET_PROVIDER = FleetDocumentProvider()
