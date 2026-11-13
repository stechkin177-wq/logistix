from django.urls import path

from .api import AccountTestView, AccountView, StatusView

urlpatterns = [
    path("api/mail/account/", AccountView.as_view()),
    path("api/mail/account/test/", AccountTestView.as_view()),
    path("api/mail/status/", StatusView.as_view()),
]
