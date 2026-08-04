from django.db import migrations, models


def migrate_legacy_plan_names(apps, schema_editor):
    User = apps.get_model("users", "User")
    User.objects.filter(plan="starter").update(plan="basic")
    User.objects.filter(plan="agency").update(plan="pro")


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0004_decimal_credit_balances"),
    ]

    operations = [
        migrations.RunPython(migrate_legacy_plan_names, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="user",
            name="plan",
            field=models.CharField(
                choices=[
                    ("free", "Free"),
                    ("basic", "Basic"),
                    ("plus", "Plus"),
                    ("pro", "Pro"),
                ],
                default="free",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="user",
            name="credits_total",
            field=models.DecimalField(decimal_places=4, default=0, max_digits=10),
        ),
        migrations.AlterField(
            model_name="user",
            name="credits_remaining",
            field=models.DecimalField(decimal_places=4, default=0, max_digits=10),
        ),
    ]

