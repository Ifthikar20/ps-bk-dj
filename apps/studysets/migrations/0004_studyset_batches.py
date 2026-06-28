from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("studysets", "0003_quizquestion_difficulty"),
    ]

    operations = [
        migrations.AddField(
            model_name="studyset",
            name="batches_total",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="studyset",
            name="batches_done",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name="studyset",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("processing", "Processing"),
                    ("partial", "Partial"),
                    ("ready", "Ready"),
                    ("failed", "Failed"),
                ],
                default="pending",
                max_length=12,
            ),
        ),
    ]
