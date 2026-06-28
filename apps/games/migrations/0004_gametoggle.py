from django.db import migrations, models

# The native, in-app games (their LearningGame.id on the client) seeded so they
# show up as ready-to-flip switches in the admin. Keep roughly in sync with the
# games registered in the Flutter app's main.dart; extra/missing rows are
# harmless (a missing row just means "enabled").
NATIVE_GAMES = [
    ("flappy_web", "Flappy Pip"),
    ("space_shooter_web", "Space Shooter"),
    ("space_hunter_web", "Space Hunter"),
    ("crossword_web", "Crossword"),
    ("super_dash", "Super Dash"),
    ("guess_the_word", "Guess the Word"),
]


def seed_native_toggles(apps, schema_editor):
    GameToggle = apps.get_model("games", "GameToggle")
    for key, label in NATIVE_GAMES:
        GameToggle.objects.get_or_create(key=key, defaults={"label": label})


def unseed_native_toggles(apps, schema_editor):
    GameToggle = apps.get_model("games", "GameToggle")
    GameToggle.objects.filter(key__in=[k for k, _ in NATIVE_GAMES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("games", "0003_game_audience_game_max_score_game_sdk_version_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="GameToggle",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "key",
                    models.SlugField(
                        help_text="Stable client id (LearningGame.id), e.g. 'flappy_web'.",
                        max_length=64,
                        unique=True,
                    ),
                ),
                (
                    "label",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Friendly name shown in this list, e.g. 'Flappy Pip'.",
                        max_length=80,
                    ),
                ),
                ("enabled", models.BooleanField(db_index=True, default=True)),
                (
                    "note",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Optional reason for the current state, for your reference.",
                        max_length=200,
                    ),
                ),
            ],
            options={
                "ordering": ("label", "key"),
            },
        ),
        migrations.RunPython(seed_native_toggles, unseed_native_toggles),
    ]
