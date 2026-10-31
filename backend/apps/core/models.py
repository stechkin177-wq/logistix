from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

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
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


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
