"""Publish (upsert) games into the catalog from JSON — the no-code way to add
a game.

A new game ships in two pushes, neither of which is an app or server code
change:

  1. Upload the game's HTML bundle to the games host so it is reachable at
     ``{GAMES_BASE_URL}/games/<slug>/index.html``.
  2. Run this command with the game's manifest JSON to insert/update its row:

         python manage.py publish_game apps/games/examples/flappy_remote.json
         python manage.py publish_game game_a.json game_b.json
         cat game.json | python manage.py publish_game -          # from stdin
         python manage.py publish_game game.json --dry-run        # validate only

The app fetches the manifest at startup and renders the game automatically —
see RemoteWebGame in the Flutter repo. JSON uses the same camelCase shape the
API serves (``coverColors``, ``minAppVersion``, ``sortOrder``), so a row can be
round-tripped straight from ``GET /api/v1/games``.
"""

import json
import sys

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.games.models import Game

# Manifest (camelCase, as served by the API) -> model field (snake_case).
FIELD_MAP = {
    "key": "key",
    "slug": "slug",
    "version": "version",
    "name": "name",
    "description": "description",
    "icon": "icon",
    "emoji": "emoji",
    "coverColors": "cover_colors",
    "difficulty": "difficulty",
    "requires": "requires",
    "minAppVersion": "min_app_version",
    "sdkVersion": "sdk_version",
    "maxScore": "max_score",
    "audience": "audience",
    "enabled": "enabled",
    "sortOrder": "sort_order",
}


class Command(BaseCommand):
    help = "Upsert games from one or more JSON manifests (file paths or '-' for stdin)."

    def add_arguments(self, parser):
        parser.add_argument(
            "sources",
            nargs="+",
            help="JSON file path(s), or '-' to read a single manifest from stdin.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate and report what would change without writing.",
        )
        parser.add_argument(
            "--skip-verify",
            action="store_true",
            help="Skip checking that the bundle exists on the games host.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        skip_verify = options["skip_verify"]
        entries = self._collect_entries(options["sources"])

        created = updated = 0
        for raw in entries:
            fields = self._to_fields(raw)
            key = fields.get("key")
            if not key:
                raise CommandError("Every game needs a non-empty 'key'.")

            existing = Game.objects.filter(key=key).first()
            instance = existing or Game()
            for attr, value in fields.items():
                setattr(instance, attr, value)

            try:
                instance.full_clean()
            except ValidationError as exc:
                raise CommandError(f"'{key}' is invalid: {exc.message_dict}")

            # Don't enable a row whose bundle isn't actually live — the #1 way a
            # publish "breaks for everyone" is a manifest/asset mismatch.
            if instance.enabled and not skip_verify:
                self._verify_bundle(instance)

            verb = "would update" if existing else "would create"
            if not dry_run:
                instance.save()
                verb = "updated" if existing else "created"
                if existing:
                    updated += 1
                else:
                    created += 1
            self.stdout.write(
                f"  {verb}: {key} -> /games/{instance.slug}/{instance.version}/"
            )

        summary = (
            f"Dry run: {len(entries)} game(s) validated, no changes written."
            if dry_run
            else f"Done: {created} created, {updated} updated."
        )
        self.stdout.write(self.style.SUCCESS(summary))

    def _collect_entries(self, sources):
        entries = []
        for src in sources:
            text = sys.stdin.read() if src == "-" else self._read_file(src)
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                raise CommandError(f"{src}: invalid JSON ({exc}).")
            # Accept a single object or a list of objects per source.
            entries.extend(data if isinstance(data, list) else [data])
        return entries

    @staticmethod
    def _read_file(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return fh.read()
        except OSError as exc:
            raise CommandError(f"Cannot read {path}: {exc}.")

    def _verify_bundle(self, game):
        """HEAD the bundle's index.html so we never enable a row whose assets
        aren't on the host yet. No-op if GAMES_BASE_URL isn't configured."""
        from urllib.error import URLError
        from urllib.request import Request, urlopen

        from django.conf import settings

        base = (getattr(settings, "GAMES_BASE_URL", "") or "").rstrip("/")
        if not base:
            self.stdout.write(
                self.style.WARNING(
                    "  (GAMES_BASE_URL unset — skipping bundle check; "
                    "use --skip-verify to silence)"
                )
            )
            return
        url = f"{base}/games/{game.slug}/{game.version}/index.html"
        try:
            req = Request(url, method="HEAD")
            with urlopen(req, timeout=10) as resp:
                if resp.status >= 400:
                    raise CommandError(f"'{game.key}': bundle not reachable ({resp.status}) at {url}")
        except URLError as exc:
            raise CommandError(
                f"'{game.key}': bundle not reachable at {url} ({exc}). "
                "Upload it first, or pass --skip-verify."
            )

    @staticmethod
    def _to_fields(raw):
        if not isinstance(raw, dict):
            raise CommandError(f"Expected a JSON object per game, got {type(raw).__name__}.")
        unknown = set(raw) - set(FIELD_MAP)
        if unknown:
            raise CommandError(
                f"Unknown field(s) {sorted(unknown)}. Allowed: {sorted(FIELD_MAP)}."
            )
        return {FIELD_MAP[k]: v for k, v in raw.items()}
