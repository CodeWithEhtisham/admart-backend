from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0002_socialaccount_external_id_socialaccount_scope_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="socialaccount",
            name="platform",
            field=models.CharField(
                choices=[
                    ("tiktok", "TikTok"),
                    ("youtube", "YouTube"),
                    ("instagram", "Instagram"),
                    ("facebook", "Facebook"),
                    ("snapchat", "Snapchat"),
                ],
                max_length=20,
            ),
        ),
    ]
