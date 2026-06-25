from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("studysets", "0002_studyset_sections"),
    ]

    operations = [
        migrations.AddField(
            model_name="quizquestion",
            name="difficulty",
            field=models.CharField(
                choices=[("easy", "Easy"), ("medium", "Medium"), ("hard", "Hard")],
                default="medium",
                max_length=8,
            ),
        ),
    ]
