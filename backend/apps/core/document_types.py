"""Типы документов техники и водителей: настройка компании (первая версия, только текст).

Стартовый набор создаётся при создании компании и правится компанией как угодно
(переименование, отключение, архив). Своих файлов/вложений нет.
"""

from __future__ import annotations

import re

from django.utils import timezone
from rest_framework import serializers

from .models import DocumentType

ALL_FIELDS = list(DocumentType.STANDARD_FIELDS)
EXTRA_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
MAX_EXTRA = 10
MAX_REMIND_DAYS = 5

# (тип, название, напоминать, за сколько дней)
DEFAULTS = {
    DocumentType.TRACTOR: [
        ("Техпаспорт", False, []),
        ("Техосмотр", True, [30, 7]),
        ("Разрешение", True, [30, 7]),
    ],
    DocumentType.TRAILER: [
        ("Техпаспорт", False, []),
        ("Техосмотр", True, [30, 7]),
        ("Разрешение", True, [30, 7]),
    ],
    DocumentType.DRIVER: [
        ("Водительское удостоверение", True, [60, 30, 7]),
        ("Удостоверение личности", False, []),
        ("Медицинская справка", True, [30, 7]),
    ],
}


def seed_document_types(company) -> None:
    """Стартовый набор типов (в контексте компании). Идемпотентно по названию.

    Если таблицы типов ещё нет (скрипты проверки миграций создают компании на промежуточной
    схеме до core.0024), набор не создаётся: миграция core.0024 заполнит его для всех компаний.
    """
    from django.db import connection

    if DocumentType._meta.db_table not in connection.introspection.table_names():
        return
    for subject, items in DEFAULTS.items():
        for order, (name, remind, days) in enumerate(items):
            DocumentType.all_objects.get_or_create(
                company=company, subject=subject, name=name, archived_at=None,
                defaults={
                    "fields": ALL_FIELDS, "remind": remind, "remind_days": days,
                    "sort_order": order,
                },
            )  # fmt: skip


def vehicle_subject(vehicle) -> str:
    return DocumentType.TRAILER if vehicle.kind == "trailer" else DocumentType.TRACTOR


def clean_config(data: dict, partial_from: DocumentType | None = None) -> dict:
    """Проверка и нормализация настроек типа (fields/required/extra/remind/remind_days)."""
    out: dict = {}
    if "fields" in data:
        fields = data["fields"]
        if not isinstance(fields, list) or not set(fields) <= set(ALL_FIELDS):
            raise serializers.ValidationError({"fields": f"Допустимо: {', '.join(ALL_FIELDS)}"})
        out["fields"] = [f for f in ALL_FIELDS if f in fields]
    shown = out.get("fields", partial_from.fields if partial_from else ALL_FIELDS)
    if "required" in data:
        required = data["required"]
        if not isinstance(required, list) or not set(required) <= set(shown):
            raise serializers.ValidationError(
                {"required": "Обязательными могут быть только показываемые поля"}
            )
        out["required"] = [f for f in ALL_FIELDS if f in required]
    elif "fields" in out and partial_from:
        out["required"] = [f for f in partial_from.required if f in shown]
    if "extra" in data:
        extra = data["extra"]
        if not isinstance(extra, list) or len(extra) > MAX_EXTRA:
            raise serializers.ValidationError({"extra": f"Не более {MAX_EXTRA} полей"})
        keys, clean = set(), []
        for item in extra:
            ok = isinstance(item, dict) and isinstance(item.get("label"), str)
            label = item["label"].strip() if ok else ""
            key = item.get("key") if ok else None
            bad_key = not isinstance(key, str) or not EXTRA_KEY_RE.match(key)
            if not label or len(label) > 60 or bad_key:
                raise serializers.ValidationError(
                    {"extra": "Поле: key (латиница, цифры, _) и название до 60 символов"}
                )
            if key in keys:
                raise serializers.ValidationError({"extra": f"Повторяется ключ {key}"})
            keys.add(key)
            clean.append({"key": key, "label": label, "required": item.get("required") is True})
        out["extra"] = clean
    if "remind" in data:
        if not isinstance(data["remind"], bool):
            raise serializers.ValidationError({"remind": "Ожидается true/false"})
        out["remind"] = data["remind"]
    if "remind_days" in data:
        days = data["remind_days"]
        valid = (
            isinstance(days, list)
            and len(days) <= MAX_REMIND_DAYS
            and all(isinstance(d, int) and not isinstance(d, bool) and 1 <= d <= 3650 for d in days)
        )
        if not valid:
            raise serializers.ValidationError(
                {"remind_days": f"До {MAX_REMIND_DAYS} чисел от 1 до 3650 (дней до окончания)"}
            )
        out["remind_days"] = sorted(set(days), reverse=True)
    remind = out.get("remind", partial_from.remind if partial_from else False)
    day_list = out.get("remind_days", partial_from.remind_days if partial_from else [])
    shown_fields = out.get("fields", shown)
    if remind and not day_list:
        raise serializers.ValidationError({"remind_days": "Укажите сроки предупреждений"})
    if remind and "expires_at" not in shown_fields:
        raise serializers.ValidationError(
            {"remind": "Для напоминаний нужно поле «Дата окончания действия»"}
        )
    return out


def validate_record(doc_type: DocumentType, values: dict) -> dict:
    """Проверка записи по настройкам типа. values: стандартные поля + extra (dict).

    Возвращает очищенный extra. Скрытые поля должны быть пустыми, обязательные - заполнены.
    """
    errors: dict = {}
    for name in DocumentType.STANDARD_FIELDS:
        value = values.get(name)
        empty = value in (None, "")
        if name not in doc_type.fields and not empty:
            errors[name] = "Поле не используется в этом типе документа"
        elif name in doc_type.required and empty:
            errors[name] = "Обязательное поле"
    extra = values.get("extra") or {}
    if not isinstance(extra, dict):
        raise serializers.ValidationError({"extra": "Ожидается объект"})
    known = {e["key"]: e for e in doc_type.extra}
    clean = {}
    for key, value in extra.items():
        if key not in known:
            errors["extra"] = f"Неизвестное поле {key}"
        elif value is not None and (not isinstance(value, str) or len(value) > 255):
            errors["extra"] = f"{known[key]['label']}: текст до 255 символов"
        elif value not in (None, ""):
            clean[key] = value
    for key, item in known.items():
        if item.get("required") and key not in clean:
            errors["extra"] = f"{item['label']}: обязательное поле"
    if errors:
        raise serializers.ValidationError(errors)
    return clean


def archive(doc_type: DocumentType) -> None:
    doc_type.archived_at = timezone.now()
    doc_type.is_active = False
    doc_type.save(update_fields=["archived_at", "is_active"])


def validate_with_type(attrs: dict, instance, subject: str, issued_attr: str) -> dict:
    """Проверка записи документа по настройкам типа (если тип задан; старые записи - как были).

    issued_attr - имя поля даты выдачи в модели (issued_at / starts_at), comment хранится в notes.
    """
    doc_type = attrs["doc_type"] if "doc_type" in attrs else getattr(instance, "doc_type", None)
    if doc_type is None:
        return attrs
    if doc_type.subject != subject:
        raise serializers.ValidationError({"doc_type": "Тип относится к другому виду объектов"})
    changed = instance is None or instance.doc_type_id != doc_type.pk
    if changed and (not doc_type.is_active or doc_type.archived_at):
        raise serializers.ValidationError({"doc_type": "Тип документа отключён"})

    def current(name, attr):
        if attr in attrs:
            return attrs[attr]
        return getattr(instance, attr, None) if instance is not None else None

    values = {
        "number": current("number", "number"),
        "issued_by": current("issued_by", "issued_by"),
        "issued_at": current("issued_at", issued_attr),
        "expires_at": current("expires_at", "expires_at"),
        "comment": current("comment", "notes"),
        "extra": current("extra", "extra"),
    }
    attrs["extra"] = validate_record(doc_type, values)
    return attrs
