from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.permissions import ModuleRequired
from apps.core.api_permissions import permission_required

from .. import access, pdf, providers


class CapabilitiesView(APIView):
    """GET /api/documents/capabilities/ -> {"pdf_available": bool}."""

    def get_permissions(self):
        return [ModuleRequired("documents")(), permission_required("documents.view")()]

    def get(self, request):
        return Response({"pdf_available": pdf.pdf_available()})


class KindsView(APIView):
    """GET /api/documents/kinds/ -> {"available_kinds": [...]}.

    Виды документов, доступные компании по включённым модулям поставщиков (реестр поставщиков).
    """

    def get_permissions(self):
        return [ModuleRequired("documents")(), permission_required("documents.view")()]

    def get(self, request):
        return Response({"available_kinds": providers.available_kinds(access.effective_modules())})
