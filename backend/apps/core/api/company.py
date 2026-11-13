"""Настройки компании: GET/PATCH /api/company/settings/ (company.view / company.update)."""

from functools import lru_cache
from zoneinfo import available_timezones

from django.db import transaction
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api_permissions import permission_required
from apps.core.audit import services as audit
from apps.core.audit.retention import login_retention_days, set_login_retention_days
from apps.core.models import Company

LANGUAGES = ["ru", "kk"]
FIELDS = ("name", "accounting_start", "timezone", "language")
RETENTION_MIN, RETENTION_MAX = 30, 1095


@lru_cache(maxsize=1)
def _zones() -> frozenset:
    return frozenset(available_timezones())


class CompanySettingsSerializer(serializers.ModelSerializer):
    language = serializers.ChoiceField(choices=LANGUAGES)

    class Meta:
        model = Company
        fields = list(FIELDS)
        extra_kwargs = {"accounting_start": {"required": False, "allow_null": True}}

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Название не может быть пустым")
        return value

    def validate_timezone(self, value):
        if value not in _zones():
            raise serializers.ValidationError(
                "Неизвестный часовой пояс (IANA, например Asia/Almaty)"
            )
        return value


class CompanySettingsView(APIView):
    def get_permissions(self):
        code = "company.update" if self.request.method == "PATCH" else "company.view"
        return [permission_required(code)()]

    def _data(self, serializer):
        # срок хранения входов - в отдельной таблице настроек журнала, в ответе вместе с остальным
        return {**serializer.data, "login_audit_retention_days": login_retention_days()}

    def get(self, request):
        company = Company.objects.get(pk=request.membership.company_id)
        return Response(self._data(CompanySettingsSerializer(company)))

    def patch(self, request):
        with transaction.atomic():
            company = Company.objects.select_for_update().get(pk=request.membership.company_id)
            before = {f: getattr(company, f) for f in FIELDS}
            days = self._retention(request.data)
            serializer = CompanySettingsSerializer(company, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            company = serializer.save()
            after = {f: getattr(company, f) for f in FIELDS}
            if days is not None:
                before["login_audit_retention_days"] = login_retention_days()
                after["login_audit_retention_days"] = set_login_retention_days(days)
            changes = audit.diff(before, after)
            if changes:
                audit.log("update", company, request.user, changes, ip=audit.client_ip(request))
        return Response(self._data(serializer))

    @staticmethod
    def _retention(data):
        if not hasattr(data, "get") or "login_audit_retention_days" not in data:
            return None
        value = data["login_audit_retention_days"]
        if isinstance(value, bool) or not isinstance(value, int):
            raise serializers.ValidationError({"login_audit_retention_days": "Нужно целое число"})
        if not RETENTION_MIN <= value <= RETENTION_MAX:
            raise serializers.ValidationError(
                {
                    "login_audit_retention_days": (
                        f"Допустимо от {RETENTION_MIN} до {RETENTION_MAX} дней"
                    )
                }
            )
        return value
