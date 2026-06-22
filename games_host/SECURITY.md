# Games host — security & operations runbook

Pushing live code to S3 with no App Store review means **the bucket and the
publish pipeline are now the security boundary**. This documents the guardrails.

## 1. Lock down the bucket (least privilege)

- A **publish** role (CI) with write to `games/*` and `playstudy-sdk.js` only.
- A **read** path via CloudFront (Origin Access Control); the bucket itself is
  **not** public. Humans don't get long-lived write keys.
- Turn on **versioning** + access logging on the bucket so every change is
  auditable and recoverable.

Example tight bucket policy (CloudFront-only read, CI-only write):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CloudFrontRead",
      "Effect": "Allow",
      "Principal": { "Service": "cloudfront.amazonaws.com" },
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::YOUR_BUCKET/*",
      "Condition": { "StringEquals": { "AWS:SourceArn": "arn:aws:cloudfront::ACCT:distribution/DIST_ID" } }
    },
    {
      "Sid": "CIPublishOnly",
      "Effect": "Allow",
      "Principal": { "AWS": "arn:aws:iam::ACCT:role/games-publisher" },
      "Action": ["s3:PutObject", "s3:DeleteObject"],
      "Resource": ["arn:aws:s3:::YOUR_BUCKET/games/*", "arn:aws:s3:::YOUR_BUCKET/playstudy-sdk.js"]
    }
  ]
}
```

## 2. Response headers (set on upload / CloudFront)

- **Game bundles** (`games/<slug>/<version>/*`) are immutable — version is in
  the path — so cache hard and add a CSP that boxes the game in:

  ```
  Cache-Control: public, max-age=31536000, immutable
  Content-Security-Policy: default-src 'none'; script-src 'self' 'unsafe-inline';
      style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' data:;
      connect-src 'none'; frame-ancestors *
  ```
  `connect-src 'none'` means a game **cannot phone home / exfiltrate** the
  injected quiz/words — it talks only to the app via the SDK bridge.
- **Manifest/index** never needs `connect-src` opened unless a specific game
  must call an allow-listed API; do that per-game, not globally.

## 3. Versioning & rollback

- Bundles live at `games/<slug>/<version>/index.html` (immutable). The manifest
  row's `version` selects which one is live.
- **Deploy:** upload `…/<newVersion>/`, then `publish_game` with the bumped
  `version` (it HEAD-checks the bundle exists before enabling).
- **Rollback:** set the row's `version` back (admin or `publish_game`) — instant,
  no re-upload, no release.

## 4. Kill switch & canary

- **Kill switch:** `enabled=false` (admin or `publish_game`) removes a game from
  the manifest immediately.
- **Canary:** publish with `audience=beta`; only clients asking for the beta
  channel see it. Promote to `stable` once it's proven.
- **Version gate:** `minAppVersion` / `sdkVersion` hide games an older app can't
  run instead of letting them break.

## 5. Trust boundaries (already enforced in code)

- The game **never receives the user's auth token** — the app makes all API
  calls; the game only gets quiz/words and emits SDK events.
- **Points are recomputed + capped server-side**; scores are **clamped to the
  game's `maxScore`** — a tampered bundle can't mint points or poison the board.
- The web host **pins postMessage to the bundle origin** and rejects messages
  from any other window/origin; the iframe sandbox withholds same-origin trust.

## 6. Publish checklist

1. Test the bundle standalone in a browser (`index.html?quiz=…` / `?words=…`).
2. Upload to `games/<slug>/<version>/`; upload the SDK if it changed.
3. `publish_game game.json` (verifies the bundle is reachable). Canary with
   `audience=beta` first if it's risky.
4. Watch `GameTelemetry` (admin) for `load_failed` / `error` after rollout.
5. Promote to `stable`, or roll back the `version` / set `enabled=false`.
