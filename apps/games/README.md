# games — S3-published games + play tracking

Games are **web bundles hosted on S3**, published with no app release and run
identically on iOS (WebView) and web (iframe). This app provides the catalog
(manifest) the clients read, and the server-owned play tracking.

## Publishing a game (no app release)

Two pushes — neither is app or backend code:

```bash
# 1. upload the bundle to its immutable versioned path (+ the SDK, once)
aws s3 sync games_host/ s3://$GAMES_BUCKET/ --exclude "*.md" --exclude "*.svg"

# 2. add/update the catalog row (HEAD-checks the bundle is reachable first)
python manage.py publish_game apps/games/examples/quiz_rush.json
```

The app fetches `GET /api/v1/games` at startup and registers each enabled row,
so the game appears on iOS and web on the next launch. Bundles load from
`{gamesBaseUrl}/games/<slug>/<version>/index.html`. Flip `enabled` to pull a
game instantly. See `games_host/README.md` (SDK + reference games) and
`games_host/SECURITY.md` (bucket lockdown, CSP, rollback runbook).

### Manifest (`GET /games`, unauthenticated catalog)

camelCase fields: `key`, `slug`, `version`, `name`, `description`, `icon`,
`emoji`, `coverColors`, `difficulty`, `requires` (`{"quiz":1}`/`{"words":2}`),
`minAppVersion`, `sdkVersion`. Server-only: `maxScore` (score clamp),
`audience` (`stable`/`beta`), `enabled`, `sortOrder`. Edit via Django admin or
`publish_game`.

Hardening built in:
- **Versioned immutable bundles** + rollback (`version` path segment).
- **Channels:** `?channel=beta` returns beta games for canarying; default is
  stable only.
- **SDK gate:** clients hide games whose `sdkVersion` exceeds what they support.
- **Publish verification:** `publish_game` HEAD-checks the bundle exists before
  enabling (skip with `--skip-verify`; needs `GAMES_BASE_URL` set).
- **Telemetry:** `POST /games/telemetry` records `loaded`/`load_failed`/`error`
  from the host so a broken bundle is visible (see GameTelemetry in admin).

### Turning games on/off — including the native, in-app games

`GET /games` only covers the **hosted** bundles above. The **native** games
(Flappy Pip, the space shooters, the crossword, Super Dash, Guess the Word) are
Flutter code compiled into the app and are normally always-on. To pull or
restore one **without an app release**, use the **GameToggle** switch board:

- Django admin → **Game toggles**: one row per game, keyed by its client id
  (`flappy_web`, `space_shooter_web`, … — the native keys are seeded for you).
  Untick `enabled` + Save to pull it; tick it back to restore.
- The app reads `GET /api/v1/games/flags` (`[{key, enabled}]`) at startup and
  unregisters any key marked `enabled: false`.
- **Fail-open:** a missing row, or an unreachable server, means the game stays
  on — so this can never accidentally hide your whole catalog.
- A disabled flag overrides a *hosted* game too (catch-all kill-switch); hosted
  games are otherwise switched via the manifest `enabled` field above.

## Play tracking + cross-platform scores

The host forwards each game's SDK events here, so play history, save-state and
scores live on the server and reflect across iOS and web:

```
POST   /api/v1/games/sessions/                 start    {gameKey, studySetId?}
PATCH  /api/v1/games/sessions/{id}/            heartbeat {score?, progress?}
POST   /api/v1/games/sessions/{id}/complete/   finalize  {score?}
GET    /api/v1/games/sessions/                 my history (?gameKey= &status=)
```

Points are **not** minted here — gameplay rewards flow through the rewards
engine (`POST /rewards/activity`) on the real in-game event, keeping one
forgery-resistant source of points. The client-reported `score` is **clamped to
the game's `maxScore`** on completion so a tampered bundle can't poison scores.
