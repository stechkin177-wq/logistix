from django.db.models import Count
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.billing.permissions import ModuleRequired
from apps.core.api_permissions import permission_required
from apps.core.audit import services as audit
from apps.core.audit.mixins import AuditedMixin

from .. import catalog, engine, services
from ..errors import DocumentError
from ..models import KINDS, DocumentTemplate
from .http import TemplateUploadThrottle, file_response
from .serializers import TemplatePatchSerializer, template_data

PERMISSIONS = {
    "list": "documents.view",
    "placeholders": "documents.view",
    "download": "documents.view",
    "partial_update": "documents.update",
    "versions": "documents.update",
    "reset": "documents.update",
}


class TemplateViewSet(AuditedMixin, viewsets.GenericViewSet):
    """Шаблоны документов компании: /api/documents/templates/."""

    parser_classes = [JSONParser, MultiPartParser, FormParser]
    pagination_class = None

    def get_permissions(self):
        code = PERMISSIONS.get(self.action, "documents.delete")
        return [ModuleRequired("forwarding")(), permission_required(code)()]

    def get_throttles(self):
        if self.action == "versions":
            return [TemplateUploadThrottle()]
        return super().get_throttles()

    def get_queryset(self):
        return (
            DocumentTemplate.objects.select_related(
                "current_version", "current_version__uploaded_by"
            )
            .defer("current_version__content")
            .annotate(versions_count=Count("versions"))
        )

    def respond(self, template, code=status.HTTP_200_OK):
        return Response(template_data(self.get_queryset().get(pk=template.pk)), status=code)

    def list(self, request):
        return Response([template_data(t) for t in self.get_queryset()])

    def partial_update(self, request, pk=None):
        template = self.get_object()
        ser = TemplatePatchSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        if data.get("is_active") is False and "documents.delete" not in (
            request.membership.role.permissions
        ):
            raise PermissionDenied("Недостаточно прав для отключения шаблона")
        before = audit.snapshot(template)
        if data.get("is_active") and not template.is_active:
            clash = DocumentTemplate.objects.filter(
                kind=template.kind, language=template.language, is_active=True
            ).exclude(pk=template.pk)
            if clash.exists():
                raise ValidationError(
                    {"is_active": "Для этого вида и языка уже есть активный шаблон."}
                )
        for field, value in data.items():
            setattr(template, field, value)
        template.save(update_fields=list(data) or None)
        self.audit_updated(before, template)
        return self.respond(template)

    @action(detail=True, methods=["post"], url_path="versions")
    def versions(self, request, pk=None):
        template = self.get_object()
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": "Приложите файл шаблона (.docx)."})
        if upload.size > engine.MAX_TEMPLATE_BYTES:
            raise DocumentError("template_too_large", "Файл шаблона больше 2 МБ.")
        data = upload.read(engine.MAX_TEMPLATE_BYTES + 1)
        if len(data) > engine.MAX_TEMPLATE_BYTES:
            raise DocumentError("template_too_large", "Файл шаблона больше 2 МБ.")
        services.upload_version(template, data, request.user)
        return self.respond(template, status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="reset")
    def reset(self, request, pk=None):
        template = self.get_object()
        services.reset_to_starter(template, request.user)
        return self.respond(template)

    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request, pk=None):
        template = DocumentTemplate.objects.select_related("current_version").get(
            pk=self.get_object().pk
        )
        version = template.current_version
        if version is None:
            raise DocumentError("template_missing", "У шаблона нет файла.")
        name = services.safe_filename(
            f"{template.kind}-{template.language}", f"v{version.number}", "docx"
        )
        return file_response(bytes(version.content), services.DOCX_TYPE, name)

    @action(detail=False, methods=["get"], url_path="placeholders")
    def placeholders(self, request):
        kind = request.query_params.get("kind", "")
        if kind not in KINDS:
            raise ValidationError({"kind": f"Допустимо: {', '.join(KINDS)}"})
        return Response(catalog.placeholders(kind))
