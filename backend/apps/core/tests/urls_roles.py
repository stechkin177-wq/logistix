"""URLconf для тестов прав: боевые маршруты плюс тестовый защищённый эндпоинт."""

from django.urls import path
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api_permissions import permission_required
from config.urls import urlpatterns as base_patterns


class OrderCreateProbe(APIView):
    permission_classes = [permission_required("orders.create")]

    def post(self, request):
        return Response({"ok": True})


urlpatterns = [*base_patterns, path("api/_probe/orders/", OrderCreateProbe.as_view())]
