from django.utils import timezone
from rest_framework import serializers
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Plan
from .services import days_left, effective_status, get_subscription


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = ["code", "name", "billing_type", "limits", "modules", "options"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # служебные метки миграций (ключи с «_») наружу не отдаются
        options = data["options"] or {}
        data["options"] = {k: v for k, v in options.items() if not k.startswith("_")}
        return data


class PlanListView(ListAPIView):
    serializer_class = PlanSerializer
    pagination_class = None
    queryset = Plan.objects.filter(is_active=True).order_by("id")


class SubscriptionView(APIView):
    def get(self, request):
        sub = get_subscription(request.membership.company_id)
        now = timezone.now()
        return Response(
            {
                "plan": PlanSerializer(sub.plan).data,
                "status": effective_status(sub, now),
                "is_free_period": sub.is_free_period,
                "starts_at": sub.starts_at,
                "ends_at": sub.ends_at,
                "days_left": days_left(sub, now),
            }
        )
