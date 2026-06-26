from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="usage_period_start",
            field=models.DateField(blank=True, null=True),
        ),
    ]
