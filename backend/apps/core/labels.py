"""Метки: размечаемые объекты, массовая загрузка для списков, замена набора, фильтр списка."""

from django.apps import apps
from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.core.audit import services as audit

from .models import Label, LabelAssignment

MAX_LABELS_PER_SUBJECT = 20

# короткое имя в адресе -> (метка модели, раздел прав объекта)
SUBJECTS = {
    "order": ("forwarding.order", "orders"),
    "trip": ("forwarding.trip", "trips"),
    "client": ("forwarding.client", "clients"),
    "carrier": ("forwarding.carrier", "carriers"),
}
SECTION_OF = {label: section for label, section in SUBJECTS.values()}


def short_label(label: Label) -> dict:
    return {"id": label.pk, "name": label.name, "color": label.color}


def labels_map(subject_type: str, ids) -> dict[int, list[dict]]:
    """{id объекта: [метки]} одним запросом (для страницы списка)."""
    rows = (
        LabelAssignment.objects.filter(subject_type=subject_type, subject_id__in=list(ids))
        .select_related("label")
        .order_by("label__name", "label_id")
    )
    out: dict[int, list[dict]] = {}
    for row in rows:
        out.setdefault(row.subject_id, []).append(short_label(row.label))
    return out


def serialize_labels(serializer, obj, subject_type: str) -> list[dict]:
    """Метки объекта для поля `labels` сериализатора; в списке грузятся разом для всей страницы."""
    cache = serializer.context.setdefault("_labels_cache", {})
    entry = cache.get(subject_type)
    if entry is None:
        parent = serializer.parent
        instances = getattr(parent, "instance", None) if hasattr(parent, "child") else None
        ids = {o.pk for o in instances} if instances is not None else {obj.pk}
        entry = cache[subject_type] = {"ids": ids, "map": labels_map(subject_type, ids)}
    if obj.pk not in entry["ids"]:  # объект вне загруженной страницы (например, после создания)
        entry["map"].update(labels_map(subject_type, [obj.pk]))
        entry["ids"].add(obj.pk)
    return entry["map"].get(obj.pk, [])


def apply_label_filter(qs, params):
    """?label=<id>: только объекты с этой меткой."""
    value = params.get("label")
    if value in (None, ""):
        return qs
    if not value.isascii() or not value.isdigit():
        raise ValidationError({"label": "Ожидается числовой id"})
    subject_type = qs.model._meta.label_lower
    ids = LabelAssignment.objects.filter(label_id=int(value), subject_type=subject_type).values(
        "subject_id"
    )
    return qs.filter(pk__in=ids)


@transaction.atomic
def set_labels(subject_type: str, subject, label_ids, user, *, ip=None) -> list[dict]:
    """Заменяет набор меток объекта. Пишет аудит объекта (названия до и после)."""
    wanted = list(dict.fromkeys(label_ids))
    if len(wanted) > MAX_LABELS_PER_SUBJECT:
        raise ValidationError({"labels": f"Не больше {MAX_LABELS_PER_SUBJECT} меток на объект"})
    found = {label.pk: label for label in Label.objects.filter(pk__in=wanted)}
    if set(found) != set(wanted):
        raise ValidationError({"labels": "Метка не найдена в вашей компании"})
    current = {
        a.label_id: a
        for a in LabelAssignment.objects.filter(
            subject_type=subject_type, subject_id=subject.pk
        ).select_related("label")
    }
    before = sorted(a.label.name for a in current.values())
    for label_id, row in current.items():
        if label_id not in found:
            row.delete()
    for label_id in wanted:
        if label_id not in current:
            LabelAssignment.objects.create(
                label=found[label_id],
                subject_type=subject_type,
                subject_id=subject.pk,
                assigned_by=user,
            )
    after = sorted(found[i].name for i in wanted)
    if before != after:
        audit.log("update", subject, user, {"labels": [before, after]}, ip=ip)
    return [short_label(found[i]) for i in sorted(wanted, key=lambda i: found[i].name)]


def subject_for(kind: str, pk: int):
    """(метка модели, раздел прав, объект) по короткому имени; объект - только своей компании."""
    if kind not in SUBJECTS:
        return None
    model_label, section = SUBJECTS[kind]
    obj = apps.get_model(model_label).objects.filter(pk=pk).first()
    return model_label, section, obj
