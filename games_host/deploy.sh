#!/usr/bin/env bash
#
# Publish PlayStudy games: sync the games host to S3 with correct cache headers,
# invalidate CloudFront, and (optionally) upsert the manifest rows.
#
# This is the single "publish a game" entry point — run it locally or from CI.
#
# Required env:
#   GAMES_BUCKET        S3 bucket name (e.g. playstudy-games)
# Optional env:
#   CLOUDFRONT_DIST_ID  CloudFront distribution to invalidate after sync
#   GAMES_BASE_URL      public origin; if set, publish_game HEAD-verifies bundles
#   PUBLISH_MANIFESTS   space-separated manifest json paths to upsert
#                       (default: all apps/games/examples/*.json). Set to "none"
#                       to skip the DB step (assets-only deploy).
#
# Usage:
#   GAMES_BUCKET=playstudy-games CLOUDFRONT_DIST_ID=E123 ./games_host/deploy.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root (ps-bk-dj)
HOST_DIR="$ROOT/games_host"

: "${GAMES_BUCKET:?set GAMES_BUCKET}"

echo "==> 1/4  Generating bundle.json for every bundle"
( cd "$HOST_DIR" && node tools/gen-bundle-json.mjs )

echo "==> 2/4  Syncing immutable game bundles to s3://$GAMES_BUCKET/games/"
# Versioned, content-addressed paths -> cache hard, forever.
aws s3 sync "$HOST_DIR/games" "s3://$GAMES_BUCKET/games" \
  --delete \
  --exclude "*.md" \
  --cache-control "public, max-age=31536000, immutable"

echo "==> 3/4  Uploading shared SDK + service worker (short cache, they're mutable)"
# These live at fixed paths, so they must NOT be cached long.
aws s3 cp "$HOST_DIR/playstudy-sdk.js" "s3://$GAMES_BUCKET/playstudy-sdk.js" \
  --cache-control "public, max-age=300, must-revalidate"
aws s3 cp "$HOST_DIR/sw.js" "s3://$GAMES_BUCKET/sw.js" \
  --cache-control "no-cache"

if [ -n "${CLOUDFRONT_DIST_ID:-}" ]; then
  echo "    Invalidating CloudFront /playstudy-sdk.js /sw.js"
  aws cloudfront create-invalidation \
    --distribution-id "$CLOUDFRONT_DIST_ID" \
    --paths "/playstudy-sdk.js" "/sw.js" >/dev/null
fi

echo "==> 4/4  Upserting manifest rows"
MANIFESTS="${PUBLISH_MANIFESTS:-$ROOT/apps/games/examples/*.json}"
if [ "$MANIFESTS" = "none" ]; then
  echo "    PUBLISH_MANIFESTS=none — skipping DB step (assets only)."
else
  # publish_game HEAD-checks each bundle is live (when GAMES_BASE_URL is set)
  # before enabling the row, so a manifest/asset mismatch can't go live.
  # shellcheck disable=SC2086
  python "$ROOT/manage.py" publish_game $MANIFESTS
fi

echo "==> Done. Games are live; apps pick them up on next launch."
