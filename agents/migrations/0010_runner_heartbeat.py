from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agents', '0009_merge_0008_clip_maker_0008_growth_report'),
    ]

    operations = [
        migrations.CreateModel(
            name='RunnerHeartbeat',
            fields=[
                ('id', models.PositiveSmallIntegerField(default=1, primary_key=True, serialize=False)),
                ('seen_at', models.DateTimeField()),
            ],
        ),
    ]
