from django.db import migrations, models


def to_role(apps, schema_editor):
    # прежний булев признак был единственным: сохранённым платформенным администраторам
    # даём роль владельца (дальше роли назначаются командой set_platform_role)
    User = apps.get_model("core", "User")
    User.objects.filter(is_platform_admin=True).update(platform_role="owner")


def to_flag(apps, schema_editor):
    User = apps.get_model("core", "User")
    User.objects.exclude(platform_role="").update(is_platform_admin=True)


class Migration(migrations.Migration):
    dependencies = [("core", "0022_fleet_permissions")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="platform_role",
            field=models.CharField(
                blank=True,
                choices=[("owner", "Владелец платформы"), ("admin", "Администратор платформы")],
                default="",
                max_length=16,
            ),
        ),
        migrations.RunPython(to_role, to_flag),
        migrations.RemoveField(model_name="user", name="is_platform_admin"),
    ]
