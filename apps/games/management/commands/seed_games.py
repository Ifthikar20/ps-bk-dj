"""Publish the bundled example games whose HTML bundle actually exists locally,
so every game listed in dev can really be played.

Wraps `publish_game` over apps/games/examples/*.json with --skip-verify, but
only for games whose games_host/games/<slug>/<version>/index.html is present.
Any already-published game missing its bundle is disabled so it doesn't show
up as a broken tile. Idempotent.

    python manage.py seed_games
"""

import json
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

from apps.games.models import Game


class Command(BaseCommand):
    help = "Publish example games that have a local bundle; disable the rest."

    def handle(self, *args, **opts):
        examples = Path(__file__).resolve().parents[2] / "examples"
        host = Path(settings.BASE_DIR) / "games_host" / "games"

        playable, skipped = [], []
        for path in sorted(examples.glob("*.json")):
            try:
                data = json.loads(path.read_text())
            except json.JSONDecodeError:
                continue
            slug = data.get("slug", "")
            version = str(data.get("version", ""))
            bundle = host / slug / version / "index.html"
            if bundle.exists():
                playable.append(str(path))
            else:
                skipped.append(slug)

        if playable:
            call_command("publish_game", *playable, skip_verify=True)
            self.stdout.write(self.style.SUCCESS(f"Seeded {len(playable)} game(s)."))

        # Hide any game (already in the DB) that has no local bundle.
        for slug in skipped:
            Game.objects.filter(slug=slug, enabled=True).update(enabled=False)
            self.stdout.write(
                self.style.WARNING(f"  no local bundle for '{slug}' — disabled.")
            )
