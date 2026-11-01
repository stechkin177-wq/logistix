"""Оформление: GET/PATCH /api/company/branding/ и публичный GET /api/branding/?host=."""

from django.db import transaction
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.core import branding as rules
from apps.core.api_permissions import permission_required
from apps.core.audit import services as audit
from apps.core.models import CompanyBranding

EDITABLE = ("app_name", "logo", "primary_color", "theme")


class BrandingSerializer(serializers.Serializer):
    app_name = serializers.CharField(max_length=64, allow_blank=True, required=False)
    logo = serializers.FileField(
        required=False,
        allow_null=True,
        allow_empty_file=False,
        validators=[rules.validate_logo],
    )
    primary_color = serializers.CharField(validators=[rules.validate_color], required=False)
    theme = serializers.ChoiceField(choices=rules.THEMES, required=False)

    def validate_app_name(self, value):
        return value.strip()

    def validate_primary_color(self, value):
        return value.upper()

    def validate(self, attrs):
        if "logo" in attrs and attrs["logo"] in (None, ""):
            attrs["logo"] = None  # очистка логотипа
        return attrs


def _state(branding) -> dict:
    return {
        "app_name": branding.app_name,
        "primary_color": branding.primary_color,
        "theme": branding.theme,
        "logo": branding.logo.name or "",
    }


class CompanyBrandingView(APIView):
    """Оформление своей компании: чтение - company.view, правка - company.update."""

    def get_permissions(self):
        code = "company.update" if self.request.method == "PATCH" else "company.view"
        return [permission_required(code)()]

    def get(self, request):
        company_id = request.membership.company_id
        # без записи в БД на чтении: строки ещё нет - значения по умолчанию
        branding = CompanyBranding.objects.filter(company_id=company_id).first()
        return Response(rules.branding_payload(branding or CompanyBranding(), request))

    def patch(self, request):
        unknown = sorted(set(request.data) - set(EDITABLE))
        if unknown:
            raise serializers.ValidationError(
                {name: "Поле недоступно для изменения" for name in unknown}
            )
        company_id = request.membership.company_id
        old_logo = None
        with transaction.atomic():
            branding, _ = CompanyBranding.objects.get_or_create(company_id=company_id)
            branding = CompanyBranding.objects.select_for_update().get(pk=branding.pk)
            before = _state(branding)
            old_logo = branding.logo.name
            serializer = BrandingSerializer(data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            for name in ("app_name", "primary_color", "theme"):
                if name in data:
                    setattr(branding, name, data[name])
            if "logo" in data:
                if data["logo"] is None:
                    branding.logo = ""
                else:
                    branding.logo = data["logo"]
            branding.save()
            after = _state(branding)
            changes = audit.diff(before, after)
            if "logo" in changes:  # имя файла и его содержимое в аудит не пишутся
                changes["logo"] = "changed"
            if changes:
                audit.log("update", branding, request.user, changes, ip=audit.client_ip(request))
            if old_logo and old_logo != branding.logo.name:
                storage = branding.logo.storage
                transaction.on_commit(lambda: storage.delete(old_logo))
        return Response(rules.branding_payload(branding, request))


class BrandingThrottle(AnonRateThrottle):
    scope = "branding"


class PublicBrandingView(APIView):
    """Оформление экрана входа по ?host=<домен>. Без входа и без контекста компании.

    Не раскрывает id/название компании и существование домена сверх возвращаемых значений:
    неизвестный, пустой и мусорный хост дают одинаковые значения платформы.
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [BrandingThrottle]

    def get(self, request):
        raw = request.query_params.get("host") or ""
        if len(raw) > rules.HOST_MAX_LENGTH:
            raise serializers.ValidationError({"host": "Слишком длинный хост (не более 255)"})
        return Response(rules.branding_for_host(raw, request))
