from django.contrib import admin
from django.urls import path

from apps.core.api.auth import LoginView, MeView, RefreshView, SwitchCompanyView
from apps.core.views import health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health),
    path("api/auth/login/", LoginView.as_view()),
    path("api/auth/refresh/", RefreshView.as_view()),
    path("api/auth/switch-company/", SwitchCompanyView.as_view()),
    path("api/auth/me/", MeView.as_view()),
]
