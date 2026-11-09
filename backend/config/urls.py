from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.billing.api import (
    AdminPlanViewSet,
    PlanListView,
    PlatformCatalogView,
    SubscriptionView,
)
from apps.core.api.auth import (
    LoginView,
    MeView,
    PasswordChangeView,
    RefreshView,
    SwitchCompanyView,
)
from apps.core.api.branding import CompanyBrandingView, PublicBrandingView
from apps.core.api.company import CompanySettingsView
from apps.core.api.modules import (
    ActivityProfilesView,
    ApplyProfileView,
    CompanyModulesView,
    ModuleDisableView,
    ModuleEnableView,
)
from apps.core.api.roles import DepartmentViewSet, RoleViewSet
from apps.core.api.session import SessionView
from apps.core.api.trash import TrashListView, TrashRestoreView
from apps.core.api.users import MembershipViewSet
from apps.core.audit.api import AuditLogViewSet
from apps.core.handbooks.api import HandbookValueViewSet, HandbookViewSet
from apps.core.numbering.api import NumberingRuleViewSet
from apps.core.views import health
from apps.documents.api.capabilities import CapabilitiesView, KindsView
from apps.documents.api.issued import IssuedViewSet
from apps.documents.api.templates import TemplateViewSet
from apps.drivers.api import DriverDocumentViewSet, DriverViewSet
from apps.finance.api.admin import (
    CarrierExpenseView,
    EngineView,
    FinanceSettingsView,
    MigrationIssueResolveView,
    MigrationView,
    OrderFinanceView,
    PeriodReopenView,
    PeriodsView,
    StatusMappingView,
    TripFinanceView,
)
from apps.finance.api.fx import (
    CarrierDebtsExportView,
    ClientDebtsExportView,
    FxDifferencesView,
    FxRevaluationLinesView,
    FxRevaluationsView,
    FxRevaluationView,
)
from apps.finance.api.invoices import InvoiceViewSet
from apps.finance.api.ledger import ExpenseViewSet, IncomeViewSet
from apps.finance.api.operations import OperationsExportView, OperationsView
from apps.finance.api.payments import PaymentViewSet
from apps.finance.api.rates import RateViewSet
from apps.finance.api.reports import CarrierDebtsView, ClientDebtsView, SummaryView
from apps.finance.api.trips import TripExpenseLinesView
from apps.fleet.api import (
    FleetSettingsView,
    FuelFillViewSet,
    InsuranceViewSet,
    MileageViewSet,
    RemindersView,
    ServiceRecordViewSet,
    VehicleDocumentViewSet,
    VehicleViewSet,
)
from apps.forwarding.api import CarrierViewSet, ClientViewSet
from apps.forwarding.consignments.api import ConsignmentViewSet
from apps.forwarding.dashboard import DashboardSummaryView
from apps.forwarding.finance_lines.api import OrderServiceViewSet
from apps.forwarding.orders.api import OrderViewSet
from apps.forwarding.tracking.api import TransferViewSet
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
router.register("transfers", TransferViewSet, basename="transfer")
router.register("platform/plans", AdminPlanViewSet, basename="platform-plan")
router.register("drivers", DriverViewSet, basename="driver")
router.register("driver-documents", DriverDocumentViewSet, basename="driver-document")
router.register("vehicles", VehicleViewSet, basename="vehicle")
router.register("vehicle-documents", VehicleDocumentViewSet, basename="vehicle-document")
router.register("insurances", InsuranceViewSet, basename="insurance")
router.register("mileage", MileageViewSet, basename="mileage")
router.register("service-records", ServiceRecordViewSet, basename="service-record")
router.register("fuel-fills", FuelFillViewSet, basename="fuel-fill")
router.register("finance/invoices", InvoiceViewSet, basename="finance-invoice")
router.register("finance/payments", PaymentViewSet, basename="finance-payment")
router.register("finance/rates", RateViewSet, basename="finance-rate")
router.register("finance/incomes", IncomeViewSet, basename="finance-income")
router.register("finance/expenses", ExpenseViewSet, basename="finance-expense")
router.register("documents/templates", TemplateViewSet, basename="document-template")
router.register("documents/issued", IssuedViewSet, basename="document-issued")

urlpatterns = [
    path("api/health/", health),
    path("api/fleet/reminders/", RemindersView.as_view()),
    path("api/fleet/settings/", FleetSettingsView.as_view()),
    path("api/documents/capabilities/", CapabilitiesView.as_view()),
    path("api/documents/kinds/", KindsView.as_view()),
    path("api/finance/debts/clients/export/", ClientDebtsExportView.as_view()),
    path("api/finance/debts/carriers/export/", CarrierDebtsExportView.as_view()),
    path("api/finance/debts/clients/", ClientDebtsView.as_view()),
    path("api/finance/debts/carriers/", CarrierDebtsView.as_view()),
    path("api/finance/summary/", SummaryView.as_view()),
    path("api/finance/operations/", OperationsView.as_view()),
    path("api/finance/operations/export/", OperationsExportView.as_view()),
    path("api/finance/operations/fx-differences/", FxDifferencesView.as_view()),
    path("api/finance/fx-revaluations/<int:pk>/lines/", FxRevaluationLinesView.as_view()),
    path("api/finance/fx-revaluations/<int:pk>/", FxRevaluationView.as_view()),
    path("api/finance/fx-revaluations/", FxRevaluationsView.as_view()),
    path("api/finance/trips/<int:pk>/expense-lines/", TripExpenseLinesView.as_view()),
    path("api/finance/trips/<int:pk>/carrier-expense/", CarrierExpenseView.as_view()),
    path("api/finance/engine/", EngineView.as_view()),
    path("api/finance/settings/status-mapping/", StatusMappingView.as_view()),
    path("api/finance/settings/", FinanceSettingsView.as_view()),
    path("api/finance/periods/<int:pk>/reopen/", PeriodReopenView.as_view()),
    path("api/finance/periods/", PeriodsView.as_view()),
    path("api/finance/migration/issues/<int:pk>/resolve/", MigrationIssueResolveView.as_view()),
    path("api/finance/migration/", MigrationView.as_view()),
    path("api/orders/<int:pk>/finance/", OrderFinanceView.as_view()),
    path("api/trips/<int:pk>/finance/", TripFinanceView.as_view()),
    path("api/auth/login/", LoginView.as_view()),
    path("api/auth/refresh/", RefreshView.as_view()),
    path("api/auth/switch-company/", SwitchCompanyView.as_view()),
    path("api/auth/me/", MeView.as_view()),
    path("api/auth/password/", PasswordChangeView.as_view()),
    path("api/session/", SessionView.as_view()),
    path("api/billing/subscription/", SubscriptionView.as_view()),
    path("api/billing/plans/", PlanListView.as_view()),
    path("api/platform/catalog/", PlatformCatalogView.as_view()),
    path("api/company/modules/apply-profile/", ApplyProfileView.as_view()),
    path("api/company/modules/<slug:code>/enable/", ModuleEnableView.as_view()),
    path("api/company/modules/<slug:code>/disable/", ModuleDisableView.as_view()),
    path("api/company/modules/", CompanyModulesView.as_view()),
    path("api/activity-profiles/", ActivityProfilesView.as_view()),
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
