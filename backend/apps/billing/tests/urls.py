"""URLconf для тестов billing: боевые маршруты плюс проба модуля fleet."""

from django.urls import path
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.permissions import ModuleRequired
from config.urls import urlpatterns as base_patterns


class FleetProbe(APIView):
    permission_classes = [ModuleRequired("fleet")]

    def get(self, request):
        return Response({"ok": True})

    def post(self, request):
        return Response({"ok": True})


urlpatterns = [*base_patterns, path("api/_probe/fleet/", FleetProbe.as_view())]
