from django.db import IntegrityError, transaction
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import audit, trash
from apps.core.api_permissions import permission_required
from apps.core.pagination import StandardPagination


def _permissions(request) -> set[str]:
    membership = getattr(request, "membership", None)
    role = membership.role if membership is not None else None
    return set(role.permissions) if role is not None else set()


class TrashListView(APIView):
    """Удалённые объекты текущей компании по зарегистрированным типам (право trash.view
    и право типа)."""

    permission_classes = [permission_required("trash.view")]

    def get(self, request):
        granted = _permissions(request)
        wanted = request.query_params.get("code")
        entries = []  # (deleted_at, code, pk) - лёгкие кортежи, подписи берём только для страницы
        for code, (model, permission) in trash.registered().items():
            if permission not in granted or (wanted and code != wanted):
                continue
            entries.extend(
                (deleted_at, code, pk)
                for pk, deleted_at in model.trash.values_list("pk", "deleted_at")
            )
        entries.sort(key=lambda e: (e[0], e[1], e[2]), reverse=True)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(entries, request, view=self)
        by_code: dict[str, list] = {}
        for _, code, pk in page:
            by_code.setdefault(code, []).append(pk)
        labels = {}
        for code, pks in by_code.items():
            model = trash.get(code)[0]
            labels.update({(code, o.pk): str(o) for o in model.trash.filter(pk__in=pks)})
        results = [
            {"code": code, "id": pk, "label": labels.get((code, pk), ""), "deleted_at": deleted_at}
            for deleted_at, code, pk in page
        ]
        return paginator.get_paginated_response(results)


class TrashRestoreView(APIView):
    """Восстановление: нужны trash.update И право типа (permission из register)."""

    permission_classes = [permission_required("trash.update")]

    def post(self, request, code, pk):
        entry = trash.get(code)
        if entry is None:
            raise Http404
        model, permission = entry
        if permission not in _permissions(request):
            raise PermissionDenied()
        try:
            pk = model._meta.pk.to_python(pk)
            obj = model.trash.filter(pk=pk).first()
        except Exception:  # noqa: BLE001 - нечисловой/некорректный id = нет такого объекта
            raise Http404 from None
        if obj is None:
            raise Http404
        blocker = getattr(obj, "restore_blocker", None)  # модель может запретить восстановление
        if blocker is not None and (reason := blocker()):
            return Response({"detail": reason}, status=status.HTTP_409_CONFLICT)
        try:
            with transaction.atomic():
                obj.restore()
                audit.log("restore", obj, request.user, ip=audit.client_ip(request))
        except IntegrityError:
            return Response(
                {"detail": "Конфликт: восстановление нарушает уникальность данных"},
                status=status.HTTP_409_CONFLICT,
            )
        return Response({"code": code, "id": obj.pk, "label": str(obj)})
