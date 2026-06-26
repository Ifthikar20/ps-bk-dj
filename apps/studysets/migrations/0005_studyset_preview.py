from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("studysets", "0004_studyset_batches"),
    ]

    operations = [
        migrations.AddField(
            model_name="studyset",
            name="preview",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
