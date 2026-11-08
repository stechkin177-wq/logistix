from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

from . import branding
from .managers import AllObjectsManager, SoftDeleteManager, TenantManager
from .phone import normalize_phone
from .tenancy import NoTenantContext, TenantMismatch, get_current_company_id


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email=None, password=None, phone=None, **extra):
        user = self.model(email=email, phone=phone, **extra)
        user.normalize_contacts()
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email=None, password=None, phone=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_platform_admin", True)
        return self.create_user(email, password, phone, **extra)

    def get_by_natural_key(self, username):
        return self.get(email=username.strip().lower())


class User(AbstractBaseUser, PermissionsMixin):
    """Пользователь платформы. Нужен хотя бы один из email/phone (CHECK в БД).

    email хранится в нижнем регистре, phone - в формате +7XXXXXXXXXX; пустые значения
    сохраняются как NULL, чтобы unique не конфликтовал.
    """

    email = models.EmailField(unique=True, null=True, blank=True)
    phone = models.CharField(max_length=32, unique=True, null=True, blank=True)
    full_name = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_platform_admin = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(email__isnull=False) | Q(phone__isnull=False),
                name="user_email_or_phone",
            ),
        ]

    def __str__(self):
        return self.email or self.phone or f"user#{self.pk}"

    def normalize_contacts(self):
        self.email = (self.email or "").strip().lower() or None
        phone = (self.phone or "").strip()
        self.phone = normalize_phone(phone) if phone else None

    def clean(self):
        super().clean()
        try:
            self.normalize_contacts()
        except ValueError as exc:
            raise ValidationError({"phone": str(exc)}) from None
        if not self.email and not self.phone:
            raise ValidationError("Нужно указать email или телефон")

    def save(self, *args, **kwargs):
        self.normalize_contacts()
        super().save(*args, **kwargs)


def default_modules():
    return ["forwarding"]


class Company(models.Model):
    name = models.CharField(max_length=255)
    bin = models.CharField(max_length=12, blank=True)
    modules = models.JSONField(default=default_modules)
    timezone = models.CharField(max_length=64, default="Asia/Almaty")
    language = models.CharField(max_length=8, default="ru")
    accounting_start = models.DateField(
        null=True,
        blank=True,
        help_text="Начало учёта: раньше этой даты финансы и завершённые не считаются",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Module(models.Model):
    """Каталог модулей платформы (платформенная таблица: без company и без RLS, как billing.Plan).

    Наполняется миграцией core.0015 и админ-панелью платформы. ``requires`` - жёсткие зависимости
    (модуль технически не работает без них), ``enhances`` - мягкие связи (работает без них).
    ``is_core`` - основа: всегда включена у каждой компании и в CompanyModule не хранится.
    """

    AVAILABLE = "available"
    BETA = "beta"
    RETIRED = "retired"
    STATUSES = [(AVAILABLE, "Доступен"), (BETA, "Бета"), (RETIRED, "Выведен")]

    code = models.SlugField(max_length=32, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    sort = models.PositiveIntegerField(default=0)
    is_core = models.BooleanField(default=False)
    requires = models.JSONField(default=list, blank=True)
    enhances = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=16, choices=STATUSES, default=AVAILABLE)

    class Meta:
        ordering = ["sort", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=["available", "beta", "retired"]),
                name="module_status_valid",
            ),
        ]

    def __str__(self):
        return self.code


class ActivityProfile(models.Model):
    """Профиль деятельности: рекомендуемый стартовый набор модулей (платформенная таблица)."""

    code = models.SlugField(max_length=32, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    modules = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.code


class CompanyBranding(models.Model):
    """Оформление компании: название приложения, логотип, цвет, тема, свой домен.

    ОБЫЧНАЯ модель (не TenantModel, без RLS): публичный эндпоинт экрана входа читает её до
    появления контекста компании (принятый пробел, см. rls.py). Создаётся лениво при первой
    правке. custom_domain в API компании только читается: его задаёт платформа (этап 5).
    """

    company = models.OneToOneField(Company, on_delete=models.PROTECT, related_name="branding")
    app_name = models.CharField(max_length=64, blank=True)
    logo = models.FileField(
        upload_to=branding.logo_upload_to, blank=True, validators=[branding.validate_logo]
    )
    primary_color = models.CharField(
        max_length=7, default=branding.DEFAULT_COLOR, validators=[branding.validate_color]
    )
    theme = models.CharField(
        max_length=8, choices=branding.THEME_CHOICES, default=branding.DEFAULT_THEME
    )
    custom_domain = models.CharField(max_length=255, null=True, blank=True, unique=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(custom_domain__isnull=True)
                | (~Q(custom_domain="") & Q(custom_domain=Lower("custom_domain"))),
                name="companybranding_domain_lower",
            ),
            models.CheckConstraint(
                condition=Q(theme__in=branding.THEMES), name="companybranding_theme_valid"
            ),
        ]

    def __str__(self):
        return f"Оформление {self.company_id}"

    def save(self, *args, **kwargs):
        self.custom_domain = (self.custom_domain or "").strip().lower() or None
        super().save(*args, **kwargs)


class TenantModel(models.Model):
    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="+")

    objects = TenantManager()
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        current = get_current_company_id()
        if self.company_id is None:
            if current is None:
                raise NoTenantContext(f"Нет текущей компании для сохранения {type(self).__name__}")
            self.company_id = current
        elif current is not None and self.company_id != current:
            raise TenantMismatch(
                f"{type(self).__name__}: company_id={self.company_id}, контекст={current}"
            )
        super().save(*args, **kwargs)


class SoftDeleteModel(models.Model):
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = SoftDeleteManager()
    trash = SoftDeleteManager(deleted=True)
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False):
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at"])

    def hard_delete(self, using=None, keep_parents=False):
        return super().delete(using=using, keep_parents=keep_parents)

    def restore(self):
        self.deleted_at = None
        self.save(update_fields=["deleted_at"])


class LegalEntity(TenantModel):
    name = models.CharField(max_length=255)
    bin = models.CharField(max_length=12, blank=True)
    bank = models.CharField(max_length=255, blank=True)
    iban = models.CharField(max_length=34, blank=True)
    address = models.CharField(max_length=500, blank=True)
    is_default = models.BooleanField(default=False)

    def __str__(self):
        return self.name


class Department(TenantModel):
    name = models.CharField(max_length=255)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"], name="department_company_name_uniq"
            ),
        ]

    def __str__(self):
        return self.name


class Role(TenantModel):
    name = models.CharField(max_length=255)
    is_system = models.BooleanField(default=False)
    permissions = models.JSONField(default=list)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["company", "name"], name="role_company_name_uniq"),
        ]

    def __str__(self):
        return self.name


class Membership(models.Model):
    """Членство пользователя в компании. Роль null (старые записи) = нет прав."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="memberships")
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL, related_name="memberships"
    )
    role = models.ForeignKey(
        Role, null=True, blank=True, on_delete=models.PROTECT, related_name="memberships"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "company"], name="membership_user_company_uniq"
            ),
        ]

    def __str__(self):
        return f"{self.user} @ {self.company}"
