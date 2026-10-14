from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0005_adaccount_google"),
    ]

    operations = [
        migrations.AddField(
            model_name="publishjob",
            name="payload",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="publishjob",
            name="scheduled_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="publishjob",
            name="status",
            field=models.CharField(
                choices=[
                    ("queued", "Queued"),
                    ("draft", "Draft"),
                    ("scheduled", "Scheduled"),
                    ("running", "Running"),
                    ("succeeded", "Succeeded"),
                    ("partial", "Partial"),
                    ("failed", "Failed"),
                ],
                default="queued",
                max_length=16,
            ),
        ),
    ]
