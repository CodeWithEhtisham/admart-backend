from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("content", "0004_videojob_libraryasset_video_job_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="imagejob",
            name="credits_reserved",
            field=models.DecimalField(decimal_places=4, default=0, max_digits=10),
        ),
        migrations.AlterField(
            model_name="imagejob",
            name="credits_used",
            field=models.DecimalField(
                blank=True, decimal_places=4, max_digits=10, null=True
            ),
        ),
        migrations.AlterField(
            model_name="videojob",
            name="credits_reserved",
            field=models.DecimalField(decimal_places=4, default=0, max_digits=10),
        ),
        migrations.AlterField(
            model_name="videojob",
            name="credits_used",
            field=models.DecimalField(
                blank=True, decimal_places=4, max_digits=10, null=True
            ),
        ),
    ]
