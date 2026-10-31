from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.billing.api import PlanListView, SubscriptionView
from apps.core.api.auth import LoginView, MeView, RefreshView, SwitchCompanyView
from apps.core.api.roles import DepartmentViewSet, RoleViewSet
from apps.core.api.users import MembershipViewSet
from apps.core.handbooks.api import HandbookValueViewSet, HandbookViewSet
from apps.core.views import health

router = SimpleRouter()
router.register("roles", RoleViewSet, basename="role")
router.register("departments", DepartmentViewSet, basename="department")
router.register("users", MembershipViewSet, basename="user")
router.register("handbooks", HandbookViewSet, basename="handbook")
router.register("handbook-values", HandbookValueViewSet, basename="handbook-value")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health),
    path("api/auth/login/", LoginView.as_view()),
    path("api/auth/refresh/", RefreshView.as_view()),
    path("api/auth/switch-company/", SwitchCompanyView.as_view()),
    path("api/auth/me/", MeView.as_view()),
    path("api/billing/subscription/", SubscriptionView.as_view()),
    path("api/billing/plans/", PlanListView.as_view()),
    path("api/", include(router.urls)),
]
