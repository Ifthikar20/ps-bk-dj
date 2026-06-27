"""Publish all bundled example games into the catalog so the app has games to
list out of the box.

Wraps `publish_game` over apps/games/examples/*.json with --skip-verify (the
bundle host may not be running in local dev). Idempotent.

    python manage.py seed_games
"""

from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Publish all bundled example games into the catalog."

    def handle(self, *args, **opts):
        examples = Path(__file__).resolve().parents[2] / "examples"
        files = sorted(str(p) for p in examples.glob("*.json"))
        if not files:
            self.stdout.write(self.style.WARNING("No example games found."))
            return
        call_command("publish_game", *files, skip_verify=True)
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(files)} game(s)."))
