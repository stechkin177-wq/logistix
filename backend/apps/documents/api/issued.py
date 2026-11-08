from types import SimpleNamespace

from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.negotiation import DefaultContentNegotiation
from rest_framework.response import Response

from apps.billing.permissions import ModuleRequired
from apps.core.api_permissions import permission_required
from apps.core.pagination import StandardPagination
from apps.forwarding.orders.filters import date_param, int_param

from .. import access, providers, services
from ..errors import DocumentError
from ..issuing import issue_for_subject
from ..models import KINDS, IssuedDocument
from .http import PdfDownloadThrottle, file_response
from .serializers import IssueSerializer, issued_data

SOURCE_PERMISSION = {
    "contract": "clients.view",
    "order_request": "orders.view",
    "carrier_order": "trips.view",
    "cmr": "trips.view",
    "act": "finance.view",
    "invoice_print": "finance.view",
}
PERMISSIONS = {"list": "documents.view", "retrieve": "documents.view", "download": "documents.view"}
RELATED = ("client", "order", "trip", "invoice", "created_by")


class NoFormatOverride(DefaultContentNegotiation):
    """`?format=` здесь - формат файла (docx|pdf), а не переопределение рендерера DRF."""

    settings = SimpleNamespace(URL_FORMAT_OVERRIDE=None)


class IssuedViewSet(viewsets.GenericViewSet):
    """Журнал выданных документов: /api/documents/issued/ (без изменения и удаления)."""

    pagination_class = StandardPagination
    content_negotiation_class = NoFormatOverride

    def get_permissions(self):
        code = PERMISSIONS.get(self.action, "documents.create")
        return [ModuleRequired("documents")(), permission_required(code)()]

    def get_throttles(self):
        if self.action == "download" and self.request.query_params.get("format") == "pdf":
            return [PdfDownloadThrottle()]
        return super().get_throttles()

    def get_queryset(self):
        qs = IssuedDocument.objects.select_related(*RELATED, "template_version").defer(
            "template_version__content", "snapshot"
        )
        if self.action == "list":
            qs = self.filter(qs)
        return qs

    def filter(self, qs):
        params = self.request.query_params
        if kind := params.get("kind"):
            if kind not in KINDS:
                raise ValidationError({"kind": f"Допустимо: {', '.join(KINDS)}"})
            qs = qs.filter(kind=kind)
        for name in ("client", "order", "trip", "invoice"):
            if (value := int_param(params, name)) is not None:
                qs = qs.filter(**{f"{name}_id": value})
        if subject_type := params.get("subject_type"):
            qs = qs.filter(subject_type=subject_type)
        if (value := int_param(params, "subject_id")) is not None:
            qs = qs.filter(subject_id=value)
        if (day := date_param(params, "date_from")) is not None:
            qs = qs.filter(issue_date__gte=day)
        if (day := date_param(params, "date_to")) is not None:
            qs = qs.filter(issue_date__lte=day)
        if term := (params.get("search") or "").strip():
            qs = qs.filter(Q(number__icontains=term))
        return qs

    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response([issued_data(d) for d in page])

    def retrieve(self, request, pk=None):
        return Response(issued_data(self.get_object()))

    def create(self, request):
        data = request.data if hasattr(request.data, "get") else {}
        kind = data.get("kind")
        if not isinstance(kind, str) or kind not in KINDS:
            raise DocumentError("kind_invalid", "Неизвестный вид документа.")
        needed = SOURCE_PERMISSION.get(kind)
        if kind == "letter" and data.get("order") not in (None, ""):
            needed = "orders.view"
        subject_type = data.get("subject_type")
        if subject_type:
            provider = (
                providers.find_provider(kind, subject_type)
                if isinstance(subject_type, str)
                else None
            )
            if provider is None:
                raise DocumentError("kind_invalid", "Неизвестный вид документа или субъект.")
            access.require_module(provider.module_code)
            needed = provider.required_permission(kind)
        # доступ к источнику проверяется раньше разбора id, чтобы не раскрывать чужие записи
        if needed and needed not in request.membership.role.permissions:
            raise PermissionDenied("Нет доступа к источнику документа")
        ser = IssueSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        v = ser.validated_data
        if v.get("subject_type"):
            doc = issue_for_subject(
                v["kind"],
                v["subject_type"],
                v["subject_id"],
                user=request.user,
                language=v.get("language"),
            )
            return self._created(doc)
        doc = services.issue_document(
            v["kind"],
            user=request.user,
            client=v.get("client"),
            order=v.get("order"),
            trip=v.get("trip"),
            invoice=v.get("invoice"),
            letter=v.get("letter"),
            language=v.get("language"),
        )
        return self._created(doc)

    def _created(self, doc):
        fresh = (
            IssuedDocument.objects.select_related(*RELATED, "template_version")
            .defer("template_version__content", "snapshot")
            .get(pk=doc.pk)
        )
        return Response(issued_data(fresh), status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request, pk=None):
        fmt = request.query_params.get("format", "docx")
        if fmt not in ("docx", "pdf"):
            raise ValidationError({"format": "Допустимо: docx или pdf"})
        doc = IssuedDocument.objects.select_related("template_version").get(pk=self.get_object().pk)
        content, content_type, name = services.render_issued(doc, fmt)
        return file_response(content, content_type, name)
