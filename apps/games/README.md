# games — server-owned play tracking

Records "games I play" so play history, scores and resume save-state live on
the server (not per-client), unified across devices. Games themselves are
native Flutter (Flame) and ship with the app — there is no server-side game
catalog; the app registers its games in code (`GameRegistry`).

## Sessions API

The app reports a play by starting a session when a game opens and completing
it when the game closes:

```
POST   /api/v1/games/sessions/                 start    {gameKey, studySetId?}
PATCH  /api/v1/games/sessions/{id}/            heartbeat {score?, progress?}
POST   /api/v1/games/sessions/{id}/complete/   finalize  {score?}
GET    /api/v1/games/sessions/                 my history (?gameKey= &status=)
GET    /api/v1/games/sessions/{id}/            one play (resume from `progress`)
```

`gameKey` is the game's stable registry id (`LearningGame.id`). The `progress`
blob (≤ 32KB) is opaque save-state for resume.

Points are **not** granted here — gameplay rewards continue to flow through the
rewards engine (`POST /rewards/activity`) on the real in-game event (e.g.
"Finished a quiz"), keeping a single forgery-resistant source of points.

## Adding a new game

Games are native Flame/Flutter and live in the app repo. To add one: implement
`LearningGame`, register it once in `main.dart`, and ship an app release. See
`lib/features/games/EXAMPLE_NEW_GAME.dart.txt` in the Flutter repo.
