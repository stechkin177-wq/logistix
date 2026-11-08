from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.permissions import ModuleRequired
from apps.core.api_permissions import permission_required

from .. import pdf


class CapabilitiesView(APIView):
    """GET /api/documents/capabilities/ -> {"pdf_available": bool}."""

    def get_permissions(self):
        return [ModuleRequired("documents")(), permission_required("documents.view")()]

    def get(self, request):
        return Response({"pdf_available": pdf.pdf_available()})
