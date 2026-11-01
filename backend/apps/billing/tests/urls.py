"""URLconf для тестов billing: боевые маршруты плюс проба модуля fleet."""

from django.urls import path
from rest_framework.authentication import BaseAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.permissions import ModuleRequired
from apps.core.models import User
from config.urls import urlpatterns as base_patterns


class FleetProbe(APIView):
    permission_classes = [ModuleRequired("fleet")]

    def get(self, request):
        return Response({"ok": True})

    def post(self, request):
        return Response({"ok": True})


class NoMembershipAuth(BaseAuthentication):
    """Аутентифицирует пользователя, но не ставит request.membership."""

    def authenticate(self, request):
        user = User.objects.filter(email="nomember@x.kz").first()
        return (user, None) if user else None

    def authenticate_header(self, request):
        return "Bearer"


class NoMembershipProbe(APIView):
    authentication_classes = [NoMembershipAuth]

    def get(self, request):
        return Response({"ok": True})


urlpatterns = [
    *base_patterns,
    path("api/_probe/fleet/", FleetProbe.as_view()),
    path("api/_probe/nomembership/", NoMembershipProbe.as_view()),
]
