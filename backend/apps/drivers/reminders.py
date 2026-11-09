"""Напоминания по документам водителей: тип документа задаёт, напоминать ли и за сколько дней."""

from datetime import timedelta

from apps.fleet.services import company_today

from .models import DriverDocument


def reminders() -> list[dict]:
    today = company_today()
    out = []
    docs = DriverDocument.objects.filter(
        driver__deleted_at__isnull=True, expires_at__isnull=False, doc_type__remind=True
    ).select_related("driver", "doc_type")
    for doc in docs:
        days = max(doc.doc_type.remind_days or [0])
        if doc.expires_at < today:
            state = "overdue"
        elif doc.expires_at <= today + timedelta(days=days):
            state = "due_soon"
        else:
            continue
        out.append(
            {
                "state": state, "driver": doc.driver_id, "full_name": doc.driver.full_name,
                "title": doc.doc_type.name, "due_date": doc.expires_at,
            }
        )  # fmt: skip
    out.sort(key=lambda r: (r["state"] != "overdue", r["due_date"], r["full_name"]))
    return out
