# games_host — the PlayStudy Game SDK + game bundles

These are the **static web assets** that get deployed to the games host
(`GAMES_BASE_URL` — an S3/CloudFront bucket or the landing site's `public/`).
They are not served by Django; this directory is the source of truth that CI
uploads. Nothing here is app code — a game ships as data + assets, never a code
change in the mobile or backend repos.

```
games_host/
  playstudy-sdk.js          ->  {GAMES_BASE_URL}/playstudy-sdk.js
  games/
    quiz-rush/index.html    ->  {GAMES_BASE_URL}/games/quiz-rush/index.html
```

## The SDK

`playstudy-sdk.js` is the one contract every game speaks. It hides the
transport difference between the two hosts (see the Flutter `GameHostView`):

- **Mobile** — a `PlayStudy` JavaScript channel injected by the app's WebView.
- **Web** — `postMessage` to the parent window of the embedding `<iframe>`.

A game includes it and talks to `window.PlayStudyGame`:

```html
<script src="../../playstudy-sdk.js"></script>
<script>
  PlayStudyGame.onInit(function (material) {
    // material.quiz: [{prompt, choices, correctIndex, explanation, topic}]
    // material.words: [{word, clue}]
    startGame(material.quiz);
  });

  PlayStudyGame.score(120);                 // update score
  PlayStudyGame.progress({ level: 3 });     // save-state for resume
  PlayStudyGame.reward("Finished a quiz");  // request points (server caps them)
  PlayStudyGame.gameover(120);              // end the play (server grants reward)
  PlayStudyGame.error("asset failed");      // report a fatal error
</script>
```

The SDK reads `quiz`/`words` from the launch URL (base64url JSON) so content is
available the instant the game loads, and also accepts it pushed by the host.
`reward` reasons must be ones the backend accepts (e.g. `"Finished a quiz"`,
`"Guessed a word"`); unknown reasons are ignored server-side.

`quiz-rush/` is a complete, dependency-free reference game built on the SDK.

## Publishing a game (no code change)

```bash
# 1. upload the assets (SDK once, then each game's folder)
aws s3 sync games_host/ s3://$GAMES_BUCKET/ --exclude "*.md"

# 2. add the catalog row so the app lists it
python manage.py publish_game apps/games/examples/quiz_rush.json
```

The app fetches the manifest at startup and renders the game automatically.
See `apps/games/README.md` for the manifest fields, play-tracking API, and how
the user sees a new game.

## Testing locally

The SDK falls back to URL content, so a game runs standalone in a browser:

```
games/quiz-rush/index.html?quiz=<base64url-json>
```

Against the running app, point `--dart-define=GAMES_BASE_URL` at wherever you
serve this folder (e.g. `python -m http.server` in `games_host/`).
