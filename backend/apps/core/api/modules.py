"""Модули компании (A6): каталог и состояние, включение/отключение, профили деятельности.

GET /api/company/modules/ - каталог + состояние компании + доступность по тарифу + зависимости +
причины, по которым нельзя включить/отключить. POST /api/company/modules/{code}/enable|disable/,
POST /api/company/modules/apply-profile/, GET /api/activity-profiles/. Все эндпоинты требуют
company.manage_modules; ошибки правил - {"detail", "code", "modules"} на русском.
"""

from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.permissions import subscription_state
from apps.core import module_services as services
from apps.core.api_permissions import permission_required
from apps.core.models import ActivityProfile, Company


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")

    def validate_reason(self, value):
        return value.strip()


class DisableSerializer(ReasonSerializer):
    cascade = serializers.BooleanField(required=False, default=False)


class ApplyProfileSerializer(ReasonSerializer):
    profile = serializers.CharField(max_length=32)
    replace = serializers.BooleanField(required=False, default=False)


class ModulesBaseView(APIView):
    def get_permissions(self):
        return [permission_required("company.manage_modules")()]

    def company(self, request) -> Company:
        return Company.objects.get(pk=request.membership.company_id)

    def payload(self, request, company, **extra):
        sub, _ = subscription_state(request)
        return {
            "plan_code": sub.plan.code if sub else None,
            "modules": services.describe_modules(company, sub.plan.modules if sub else []),
            **extra,
        }


class CompanyModulesView(ModulesBaseView):
    def get(self, request):
        return Response(self.payload(request, self.company(request)))


class ModuleEnableView(ModulesBaseView):
    def post(self, request, code):
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        company = self.company(request)
        services.enable_module(company, code, request.user, data.validated_data["reason"])
        return Response(self.payload(request, company))


class ModuleDisableView(ModulesBaseView):
    def post(self, request, code):
        data = DisableSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        company = self.company(request)
        v = data.validated_data
        services.disable_module(company, code, request.user, v["reason"], cascade=v["cascade"])
        return Response(self.payload(request, company))


class ApplyProfileView(ModulesBaseView):
    def post(self, request):
        data = ApplyProfileSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        profile = ActivityProfile.objects.filter(code=v["profile"]).first()
        if profile is None:
            raise NotFound("Профиль деятельности не найден")
        company = self.company(request)
        result = services.apply_profile(
            company, profile, request.user, v["reason"], replace=v["replace"]
        )
        return Response(self.payload(request, company, result=result))


class ActivityProfilesView(ModulesBaseView):
    def get(self, request):
        company = self.company(request)
        sub, _ = subscription_state(request)
        plan = set(sub.plan.modules or []) if sub else set()
        enabled = set(services.enabled_module_codes(company.pk))
        return Response(
            [
                {
                    "code": p.code,
                    "name": p.name,
                    "description": p.description,
                    "modules": list(p.modules),
                    "unavailable_modules": [m for m in p.modules if m not in plan],
                    "already_enabled": [m for m in p.modules if m in enabled],
                }
                for p in ActivityProfile.objects.order_by("id")
            ]
        )
