from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0003_user_active_project_delete_socialaccount"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="credits_remaining",
            field=models.DecimalField(decimal_places=4, default=5, max_digits=10),
        ),
        migrations.AlterField(
            model_name="user",
            name="credits_total",
            field=models.DecimalField(decimal_places=4, default=5, max_digits=10),
        ),
        migrations.AlterField(
            model_name="user",
            name="credits_used",
            field=models.DecimalField(decimal_places=4, default=0, max_digits=10),
        ),
    ]
