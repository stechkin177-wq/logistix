from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone

from .managers import AllObjectsManager, SoftDeleteManager, TenantManager
from .tenancy import NoTenantContext, TenantMismatch, get_current_company_id


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra):
        user = self.model(email=self.normalize_email(email), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    """Минимальная модель для запуска проекта; будет переработана в Task 3."""

    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=32, blank=True)
    full_name = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    def __str__(self):
        return self.email


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
