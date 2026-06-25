# Deployment & publishing

> **For the current, real, deployed AWS state — what exists, IDs, costs,
> security posture, operator commands, gaps, roadmap — see [`INFRASTRUCTURE.md`](./INFRASTRUCTURE.md).**
> This doc describes the *intended* deploy/publish workflow at the design level.

Three things deploy independently. Only the first two are "real" deploys; new
games are just data + assets.

| What | How often | Mechanism |
|------|-----------|-----------|
| **Backend** (this repo) | per backend change | container/host deploy + `migrate` |
| **App shell** (Flutter, iOS) | rarely (only host/SDK changes) | App Store release |
| **Games** (web bundles) | anytime | `games_host/deploy.sh` → S3 + manifest |

## One-time infrastructure

- **S3 bucket** for game bundles (e.g. `playstudy-games`), private, with
  **versioning** on. Front it with **CloudFront** (Origin Access Control) — the
  bucket is never public. See `games_host/SECURITY.md` for the bucket policy,
  CSP, and cache headers.
- **AWS OIDC role** for CI to assume (write to the bucket + create
  invalidations). No long-lived keys.
- Point the app and backend at the CDN origin:
  - app build: `--dart-define=GAMES_BASE_URL=https://games.playstudy.app`
  - backend env: `GAMES_BASE_URL=https://games.playstudy.app` (so
    `publish_game` can verify a bundle is live before enabling it).

## 1. Backend deploy

```bash
pip install -r requirements.txt
python manage.py migrate              # applies games + all migrations
python manage.py collectstatic --noinput
# serve: gunicorn config.wsgi  (Celery worker + Redis + Postgres per README)
```
Backend changes (including new manifest fields) take effect immediately on
deploy — no app release.

## 2. App shell (iOS) — only when the host/SDK changes

The app is built once and shipped to the App Store. You only re-release when you
change native code: the game host, the SDK contract (`supportedSdkVersion`), or
native capabilities. **Adding or changing games never needs this.**

## 3. Publish a game (the common case — no release)

Everything is one script, `games_host/deploy.sh`:

```bash
GAMES_BUCKET=playstudy-games \
CLOUDFRONT_DIST_ID=E123ABC \
GAMES_BASE_URL=https://games.playstudy.app \
./games_host/deploy.sh
```

It: (1) generates each bundle's `bundle.json`, (2) syncs `games/` to S3 as
**immutable** (long cache), (3) uploads the SDK + `sw.js` with a short cache and
invalidates CloudFront, (4) runs `publish_game` which **HEAD-verifies each
bundle is live** before enabling its manifest row.

### In CI

`.github/workflows/publish-games.yml` runs that script on changes to
`games_host/**` or `apps/games/examples/**` (or manual dispatch). Configure:
- repo **secrets**: `AWS_ROLE_ARN`, `DATABASE_URL`, `SECRET_KEY`
- repo **variables**: `AWS_REGION`, `GAMES_BUCKET`, `CLOUDFRONT_DIST_ID`, `GAMES_BASE_URL`

If your Postgres isn't reachable from GitHub runners, set `PUBLISH_MANIFESTS=none`
in the workflow (assets-only) and run `python manage.py publish_game <json>` as a
step of your backend deploy instead.

### What the user sees

On next app launch the manifest is re-fetched; the game appears on iOS and web
and is pre-cached for offline. To **roll back**: point the manifest row's
`version` back (or `enabled=false`) and re-run — instant, no release.

## Adding a brand-new game, end to end

1. Create `games_host/games/<slug>/<version>/index.html` (+ assets) using the
   SDK; test it standalone in a browser.
2. Add `apps/games/examples/<key>.json` (manifest row).
3. Commit. CI publishes it — or run `games_host/deploy.sh` locally.
