# Games catalog — publishing a game without a code change

A new game ships as **data + an asset**, never a code change in either repo.
The app fetches the manifest (`GET /api/v1/games`) at startup and renders each
entry automatically (see `RemoteWebGame` in the Flutter app).

## The two pushes

### 1. Push the game asset to the games host

Upload the game's static HTML5 bundle so it is reachable at:

```
{GAMES_BASE_URL}/games/<slug>/index.html
```

`GAMES_BASE_URL` is the app's `--dart-define=GAMES_BASE_URL` (the landing
site's `public/games/` folder or an S3/CDN bucket). `<slug>` is the `slug`
field in the manifest below. No backend involvement — it's a static upload.

### 2. Push the row to the database

```bash
# add or update one game
python manage.py publish_game apps/games/examples/flappy_remote.json

# several at once, or straight from stdin
python manage.py publish_game game_a.json game_b.json
cat game.json | python manage.py publish_game -

# validate without writing
python manage.py publish_game game.json --dry-run
```

`publish_game` upserts by `key`, so re-running it edits the game in place.
The Django admin (`/admin/ → Games`) does the same thing by hand, including
toggling `enabled` to pull a broken game instantly — also no deploy.

## Manifest shape

camelCase, identical to what `GET /api/v1/games` returns, so a row can be
round-tripped straight from the API.

| field           | required | notes                                                        |
|-----------------|----------|--------------------------------------------------------------|
| `key`           | yes      | Stable client id. **Don't reuse a built-in native id** (e.g. use `flappy_remote`, not `flappy_web`) or it shadows the native game. |
| `slug`          | yes      | Path segment: `{GAMES_BASE_URL}/games/<slug>/index.html`.    |
| `name`          | yes      | Title on the game card.                                      |
| `description`   | yes      | One-line pitch under the title.                              |
| `icon`          | no       | Material icon name (e.g. `flutter_dash`). Unknown names fall back to `emoji`, then a generic icon. |
| `emoji`         | no       | Fallback icon.                                               |
| `coverColors`   | yes      | Two-stop gradient, e.g. `["0xFFFBC78A", "0xFFEF4444"]`.      |
| `difficulty`    | no       | `easy` \| `medium` \| `hard` (default `medium`).             |
| `requires`      | no       | Data-driven gate: `{"quiz": 1}` or `{"words": 2}`. Empty = always shown. The game only appears on study sets that have enough of that content. |
| `minAppVersion` | no       | Hide from app builds older than this semver. Blank = no minimum. |
| `enabled`       | no       | Defaults true. Set false to hide without deleting.           |
| `sortOrder`     | no       | Lower sorts first.                                           |

## The HTML game contract

The bundle is hosted in the app's `WebGameView` (a WebView). To receive the
study set's content and award points it should:

- Read `quiz` / `words` from the URL query (`?quiz=<base64url-json>&words=<base64url-json>`),
  **or** implement `window.PlayStudyInit(payload)` where
  `payload = { quiz: [...], words: [...] }` — the host calls it on load.
- Post messages to the `PlayStudy` JS channel:
  - `{"type":"ready"}` — ask the host to (re)inject the payload.
  - `{"type":"reward","reason":"<gameplay reason>"}` — the server recomputes
    and caps points; only recognized gameplay reasons are accepted.
  - `{"type":"score", ...}` / `{"type":"gameover", ...}` — handled in-game.

`quiz` items are `{prompt, choices, correctIndex, explanation, topic}`;
`words` are `{word, clue}`.

## Play tracking (games I play)

Plays are recorded server-side so history, scores and resume save-state are
unified across mobile and web (not stored per-client). The game host forwards
its SDK events here:

```
POST   /api/v1/games/sessions/                 start    {gameKey, studySetId?}
PATCH  /api/v1/games/sessions/{id}/            heartbeat {score?, progress?}
POST   /api/v1/games/sessions/{id}/complete/   finalize  {score?} -> {session, rewards}
GET    /api/v1/games/sessions/                 my history (?gameKey= &status=)
GET    /api/v1/games/sessions/{id}/            one play (resume from `progress`)
```

Completion grants points through the server-authoritative rewards engine
(reason `"Played a game"`, flat + capped, deduped on the session id so retries
never double-award). The raw game `score` is client-reported, so it never feeds
the point economy — it's kept for leaderboards only.

## How the user sees it

On the next app launch the manifest is fetched and the game is registered.
It then appears wherever the registry is shown — the home games strip, the
library games list, and the games grid of any study set whose content
satisfies `requires`. No app update or reinstall. (The catalog is read at
startup, so a game published mid-session shows on the next cold start.)
