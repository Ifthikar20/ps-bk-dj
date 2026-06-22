# games — S3-published games + play tracking

Games are **web bundles hosted on S3**, published with no app release and run
identically on iOS (WebView) and web (iframe). This app provides the catalog
(manifest) the clients read, and the server-owned play tracking.

## Publishing a game (no app release)

Two pushes — neither is app or backend code:

```bash
# 1. upload the bundle (and the SDK, once) to the games host
aws s3 sync games_host/ s3://$GAMES_BUCKET/ --exclude "*.md"

# 2. add/update the catalog row
python manage.py publish_game apps/games/examples/quiz_rush.json
```

The app fetches `GET /api/v1/games` at startup and registers each enabled row,
so the game appears on iOS and web on the next launch. Flip `enabled` to pull
a game instantly. See `games_host/README.md` for the SDK + a reference game.

### Manifest (`GET /games`, unauthenticated catalog)

camelCase fields: `key`, `slug`, `name`, `description`, `icon`, `emoji`,
`coverColors`, `difficulty`, `requires` (`{"quiz":1}` / `{"words":2}`),
`minAppVersion`. Edit in Django admin or via `publish_game`.

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
forgery-resistant source of points.
