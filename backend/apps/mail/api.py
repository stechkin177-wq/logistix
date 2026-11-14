from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.core.api_permissions import permission_required
from apps.core.audit.mixins import AuditedMixin
from apps.core.models import Company
from apps.core.pagination import StandardPagination
from apps.documents.models import IssuedDocument
from apps.forwarding.models import Client, Order, Trip

from . import crypto, services
from .models import MailAccount, MailMessage, MailTemplate


class MailSendThrottle(UserRateThrottle):
    scope = "mail_send"


# --- ящик компании ---


class AccountSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True, required=False, allow_blank=True, trim_whitespace=False
    )
    has_password = serializers.SerializerMethodField()

    class Meta:
        model = MailAccount
        fields = [
            "host", "port", "security", "username", "password", "has_password", "from_email",
            "from_name", "is_active", "updated_at",
        ]  # fmt: skip
        read_only_fields = ["updated_at"]

    def get_has_password(self, obj):
        return bool(obj.password_enc)

    def validate(self, attrs):
        host = attrs.get("host", getattr(self.instance, "host", ""))
        port = attrs.get("port", getattr(self.instance, "port", 587))
        services.validate_account_fields(host, port)
        return attrs


class AccountView(APIView):
    """Ящик компании: GET (без пароля), PUT (создать/изменить; пустой пароль - без изменения)."""

    def get_permissions(self):
        return [permission_required("mail.manage_account")()]

    def get(self, request):
        account = MailAccount.objects.first()
        if account is None:
            return Response({"configured": False})
        return Response({"configured": True, **AccountSerializer(account).data})

    def put(self, request):
        account = MailAccount.objects.first()
        ser = AccountSerializer(account, data=request.data, partial=account is not None)
        ser.is_valid(raise_exception=True)
        data = dict(ser.validated_data)
        password = data.pop("password", None)
        if account is None:
            account = MailAccount(**data)
        else:
            for key, value in data.items():
                setattr(account, key, value)
        if password:
            account.password_enc = crypto.encrypt(password)
        account.save()
        return Response({"configured": True, **AccountSerializer(account).data})


class AccountTestView(APIView):
    """Тестовое письмо на адрес самого пользователя: проверка настроек ящика."""

    throttle_classes = [MailSendThrottle]

    def get_permissions(self):
        return [permission_required("mail.manage_account")()]

    def post(self, request):
        target = request.user.email
        if not target:
            raise ValidationError(
                {"detail": "У вашей учётной записи нет email для проверочного письма"}
            )
        message = MailMessage.objects.create(
            to=[target],
            subject="Проверка почты LogistiX",
            body="Это проверочное письмо: исходящая почта компании настроена.",
            created_by=request.user,
        )
        message = services.send_message(message)
        return Response({"state": message.state, "error": message.error, "to": target})


class StatusView(APIView):
    """Можно ли писать письма: ящик настроен и включён (для интерфейса)."""

    def get_permissions(self):
        return [permission_required("mail.view")()]

    def get(self, request):
        account = MailAccount.objects.first()
        return Response(
            {
                "configured": bool(account and account.is_active),
                "from_email": account.from_email if account else "",
            }
        )


# --- шаблоны ---


class TemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = MailTemplate
        fields = ["id", "name", "subject", "body", "created_at"]
        read_only_fields = ["id", "created_at"]
        validators: list = []

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Название не может быть пустым")
        dup = MailTemplate.objects.filter(name__iexact=value)
        if self.instance is not None:
            dup = dup.exclude(pk=self.instance.pk)
        if dup.exists():
            raise serializers.ValidationError("Шаблон с таким названием уже есть")
        return value


def _context(request, order=None, trip=None, client=None) -> dict:
    company = Company.objects.get(pk=request.membership.company_id)
    carrier_name = ""
    if trip is not None and trip.carrier_id:
        carrier_name = trip.carrier.name
    client = client or (order.client if order is not None else None)
    return {
        "company_name": company.name,
        "client_name": client.name if client else "",
        "order_number": order.number if order else "",
        "trip_number": trip.number if trip else "",
        "carrier_name": carrier_name,
        "sender_name": request.user.full_name or request.user.email or "",
    }


def _linked(data):
    """order/trip/client из тела запроса (только своей компании); None, если не указаны."""
    found = {}
    for key, model in (("order", Order), ("trip", Trip), ("client", Client)):
        value = data.get(key)
        if value in (None, ""):
            found[key] = None
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationError({key: "Ожидается id"})
        obj = model.objects.filter(pk=value).first()
        if obj is None:
            raise ValidationError({key: "Запись не найдена"})
        found[key] = obj
    return found


class TemplateViewSet(AuditedMixin, viewsets.ModelViewSet):
    serializer_class = TemplateSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_permissions(self):
        if self.action == "render":  # подстановка в окне письма нужна тем, кто пишет письма
            return [permission_required("mail.send")()]
        safe = self.request.method in ("GET", "HEAD", "OPTIONS")
        return [permission_required("mail.view" if safe else "mail.manage_account")()]

    def get_queryset(self):
        return MailTemplate.objects.all()

    @action(detail=True, methods=["post"], url_path="render")
    def render(self, request, pk=None):
        template = self.get_object()
        linked = _linked(request.data if hasattr(request.data, "get") else {})
        context = _context(request, **linked)
        return Response(
            {
                "subject": services.render_template(template.subject, context),
                "body": services.render_template(template.body, context),
            }
        )


# --- письма ---


class MessageSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()
    attachments = serializers.SerializerMethodField()
    order_number = serializers.CharField(source="order.number", read_only=True, default=None)
    trip_number = serializers.CharField(source="trip.number", read_only=True, default=None)
    client_name = serializers.CharField(source="client.name", read_only=True, default=None)

    class Meta:
        model = MailMessage
        fields = [
            "id", "to", "cc", "subject", "body", "state", "error", "sent_at", "attempts", "order",
            "order_number", "trip", "trip_number", "client", "client_name", "created_by_name",
            "attachments", "created_at",
        ]  # fmt: skip
        read_only_fields = fields

    def get_created_by_name(self, obj):
        user = obj.created_by
        return (user.full_name or user.email or "") if user else ""

    def get_attachments(self, obj):
        return [
            {"id": a.pk, "document": a.document_id, "filename": a.filename}
            for a in obj.attachments.all()
        ]


class MessageViewSet(AuditedMixin, viewsets.ReadOnlyModelViewSet):
    """Письма компании: список, карточка, создание (отправка или черновик), повтор."""

    serializer_class = MessageSerializer
    pagination_class = StandardPagination

    def get_permissions(self):
        if self.action in ("create", "send"):
            return [permission_required("mail.send")()]
        return [permission_required("mail.view")()]

    def get_throttles(self):
        return (
            [MailSendThrottle()] if self.action in ("create", "send") else super().get_throttles()
        )

    def get_queryset(self):
        qs = MailMessage.objects.select_related(
            "order", "trip", "client", "created_by"
        ).prefetch_related("attachments")
        if self.action != "list":
            return qs
        params = self.request.query_params
        for field in ("order", "trip", "client"):
            value = params.get(field)
            if value:
                if not value.isdigit():
                    raise ValidationError({field: "Ожидается числовой id"})
                qs = qs.filter(**{f"{field}_id": int(value)})
        if state := params.get("state"):
            if state not in dict(MailMessage.STATES):
                raise ValidationError({"state": "Допустимо: draft, sent, failed"})
            qs = qs.filter(state=state)
        if q := (params.get("q") or "").strip():
            qs = qs.filter(subject__icontains=q)
        return qs

    def create(self, request, *args, **kwargs):
        data = request.data if hasattr(request.data, "get") else {}
        to = services.clean_addresses(data.get("to", []), "to", required=True)
        cc = services.clean_addresses(data.get("cc", []), "cc", required=False)
        subject = str(data.get("subject") or "").strip()
        body = str(data.get("body") or "")
        if not subject or len(subject) > 200 or "\n" in subject or "\r" in subject:
            raise ValidationError({"subject": "Тема обязательна, до 200 знаков, в одну строку"})
        if len(body) > 20000:
            raise ValidationError({"body": "Текст письма не длиннее 20 000 знаков"})
        linked = _linked(data)
        doc_ids = data.get("attachments", [])
        if not isinstance(doc_ids, list) or not all(
            isinstance(i, int) and not isinstance(i, bool) for i in doc_ids
        ):
            raise ValidationError({"attachments": "Ожидается список id выданных документов"})
        docs = list(
            IssuedDocument.objects.filter(pk__in=doc_ids).select_related("template_version")
        )
        if doc_ids and not request.membership.role.permissions.__contains__("documents.view"):
            raise ValidationError({"attachments": "Нет права просмотра документов"})
        if len(docs) != len(set(doc_ids)):
            raise ValidationError({"attachments": "Документ не найден"})
        message = MailMessage.objects.create(
            to=to, cc=cc, subject=subject, body=body, created_by=request.user, **linked
        )
        services.attach_documents(message, docs)
        self.audit_created(message)
        if data.get("send", True):
            services.send_message(message)
        return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="send")
    def send(self, request, pk=None):
        message = self.get_object()
        if message.state == MailMessage.SENT:
            raise ValidationError({"detail": "Письмо уже отправлено"})
        services.send_message(message)
        return Response(MessageSerializer(message).data)
