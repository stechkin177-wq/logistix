from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import platform

from .auth import companies_payload, memberships_of


class PlatformSessionView(APIView):
    """Сессия платформенного контекста: кто вошёл, роль, права, компании для переключения.

    Только платформенный токен (ctx=platform); токен компании получает
    403 platform_context_required, а платформенный токен на /api/session/ -
    403 company_context_required."""

    permission_classes = [IsAuthenticated, platform.PlatformAccess]

    def get(self, request):
        user = request.user
        return Response(
            {
                "context": platform.CTX_PLATFORM,
                "user": {
                    "id": user.pk,
                    "email": user.email,
                    "phone": user.phone,
                    "full_name": user.full_name,
                    "platform_role": request.platform_role,
                },
                "permissions": sorted(platform.ROLE_PERMISSIONS[request.platform_role]),
                "companies": companies_payload(memberships_of(user).order_by("id")),
            }
        )
