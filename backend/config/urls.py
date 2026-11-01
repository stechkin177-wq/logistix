from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.billing.api import PlanListView, SubscriptionView
from apps.core.api.auth import (
    LoginView,
    MeView,
    PasswordChangeView,
    RefreshView,
    SwitchCompanyView,
)
from apps.core.api.branding import CompanyBrandingView, PublicBrandingView
from apps.core.api.company import CompanySettingsView
from apps.core.api.roles import DepartmentViewSet, RoleViewSet
from apps.core.api.session import SessionView
from apps.core.api.trash import TrashListView, TrashRestoreView
from apps.core.api.users import MembershipViewSet
from apps.core.audit.api import AuditLogViewSet
from apps.core.handbooks.api import HandbookValueViewSet, HandbookViewSet
from apps.core.numbering.api import NumberingRuleViewSet
from apps.core.views import health
from apps.forwarding.api import CarrierViewSet, ClientViewSet
from apps.forwarding.consignments.api import ConsignmentViewSet
from apps.forwarding.dashboard import DashboardSummaryView
from apps.forwarding.finance_lines.api import OrderServiceViewSet
from apps.forwarding.orders.api import OrderViewSet
from apps.forwarding.trips.api import TripViewSet

router = SimpleRouter()
router.register("roles", RoleViewSet, basename="role")
router.register("departments", DepartmentViewSet, basename="department")
router.register("users", MembershipViewSet, basename="user")
router.register("handbooks", HandbookViewSet, basename="handbook")
router.register("numbering", NumberingRuleViewSet, basename="numbering")
router.register("audit", AuditLogViewSet, basename="audit")
router.register("handbook-values", HandbookValueViewSet, basename="handbook-value")
router.register("clients", ClientViewSet, basename="client")
router.register("carriers", CarrierViewSet, basename="carrier")
router.register("orders", OrderViewSet, basename="order")
router.register("order-lines", OrderServiceViewSet, basename="order-line")
router.register("consignments", ConsignmentViewSet, basename="consignment")
router.register("trips", TripViewSet, basename="trip")

urlpatterns = [
    path("api/health/", health),
    path("api/auth/login/", LoginView.as_view()),
    path("api/auth/refresh/", RefreshView.as_view()),
    path("api/auth/switch-company/", SwitchCompanyView.as_view()),
    path("api/auth/me/", MeView.as_view()),
    path("api/auth/password/", PasswordChangeView.as_view()),
    path("api/session/", SessionView.as_view()),
    path("api/billing/subscription/", SubscriptionView.as_view()),
    path("api/billing/plans/", PlanListView.as_view()),
    path("api/company/settings/", CompanySettingsView.as_view()),
    path("api/company/branding/", CompanyBrandingView.as_view()),
    path("api/branding/", PublicBrandingView.as_view()),
    path("api/dashboard/summary/", DashboardSummaryView.as_view()),
    path("api/trash/", TrashListView.as_view()),
    path("api/trash/<str:code>/<str:pk>/restore/", TrashRestoreView.as_view()),
    path("api/", include(router.urls)),
]

# Логотипы с локального диска: только в разработке (DEBUG); в продакшене - прокси/S3 (этап 5)
if settings.ADMIN_ENABLED:
    urlpatterns.insert(0, path("admin/", admin.site.urls))

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
