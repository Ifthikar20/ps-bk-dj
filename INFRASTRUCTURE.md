# Infrastructure & Operations

The current, real, deployed state of PlayStudy AWS infrastructure — what
exists, how it fits together, how to operate it, what's still missing.

`DEPLOY.md` describes the *intended* deploy & publish workflow. **This doc
is the source of truth for what actually exists right now.**

---

## TL;DR

| | |
|---|---|
| **Backend** | Single EC2 `t3.small` in us-east-1 running docker-compose (gunicorn + celery + postgres 16 + redis 7 + caddy) |
| **Games** | Single private S3 bucket with public-read on `/games/*` (no CloudFront yet) |
| **Domain** | None — using raw IP `100.55.196.80` as FQDN. HTTP only. |
| **CI** | GitHub Actions auto-deploys backend on push to `main`; games deploy is currently manual from a laptop |
| **Cost** | ~$22/mo total (playstudy only; fetchbot-prod is separate) |
| **Biggest gaps** | No DB backups · no HTTPS · no domain · no monitoring |

---

## Architecture

```
                         INTERNET
                            │
                ┌───────────┼───────────────────┐
                │           │                   │
            (mobile)    (browser)            (you)
                │           │                   │
                ▼           ▼                   ▼
        http://100.55.196.80                  ssh 22
                │           │                   │
                └─────┬─────┘                   │
                      ▼                         │
            ┌─────────────────┐                 │
            │   EC2 t3.small  │◄────────────────┘
            │   (Ubuntu 22)   │
            │                 │
            │  UFW: 22/80/443 │
            │  fail2ban       │
            │                 │
            │  docker-compose:│
            │   ┌───────────┐ │
            │   │   caddy   │◄── 80
            │   └─────┬─────┘
            │         │ reverse_proxy
            │   ┌─────▼─────┐ │
            │   │    web    │ │  gunicorn (Django)
            │   │  (Django) │ │
            │   └─────┬─────┘ │
            │         │       │   ┌───────────┐
            │   ┌─────▼─────┐ │   │  worker   │ celery
            │   │ postgres  │◄┼───┤  (Django) │
            │   │   :5432   │ │   └─────┬─────┘
            │   └───────────┘ │         │
            │   ┌───────────┐ │         │
            │   │   redis   │◄┴─────────┘
            │   │   :6379   │
            │   └───────────┘
            └─────────────────┘
                      │
                      │ aws s3 cp / boto3
                      ▼
            ┌───────────────────────────────────┐
            │ s3://playstudy-games-prod         │
            │   /games/<slug>/<v>/index.html    │  public read
            │   /playstudy-sdk.js                │  public read
            │   /access-logs/                    │  internal
            └───────────────────────────────────┘
```

---

## AWS resource inventory

**Account:** `817977750104` · **Region:** `us-east-1` (everything)

### EC2 / networking

| Resource | ID | Notes |
|---|---|---|
| EC2 instance | `i-0d01ec75f2cc2ca77` | t3.small, Ubuntu 22.04, 30 GB gp3 root |
| Elastic IP | `eipalloc-0012da68a3820c99a` → **`100.55.196.80`** | Sticky, never changes |
| Security group | `sg-0bf1444c4ddf2525e` (`playstudy-api-sg`) | See port table below |
| EBS volume | `vol-00643c98d77c72576` | 30 GB gp3, attached to the EC2 root |
| Key pair (admin SSH) | `playstudy-deploy` (ed25519) | Private at `~/.ssh/playstudy-deploy.pem` (chmod 400) |
| Key pair (CI SSH) | `playstudy-ci-deploy-v2` (ed25519) | Private at `~/.ssh/playstudy-ci-deploy-v2`, public also stored as GitHub repo secret `SSH_PRIVATE_KEY` |

#### Security group rules (`playstudy-api-sg`)

| Port | Protocol | IPv4 | IPv6 | Why |
|---|---|---|---|---|
| 22 | TCP | `99.98.216.124/32` + `0.0.0.0/0` | `2600:1700:1680:a580::/64` + `::/0` | SSH — global needed for GitHub Actions; protected by ed25519 key + fail2ban |
| 80 | TCP | `0.0.0.0/0` | `::/0` | HTTP (Caddy) |
| 443 | TCP | `0.0.0.0/0` | `::/0` | HTTPS (reserved for when we flip to TLS) |

### S3

| Bucket | Region | Purpose |
|---|---|---|
| `playstudy-games-prod` | us-east-1 | Game bundles + SDK + access logs |

Bucket configuration:
- **Versioning:** ON (every upload keeps history; rollback via version)
- **Public access block:** `BlockPublicAcls=true`, `BlockPublicPolicy=false`
- **Bucket policy:**
  - `s3:GetObject` public on `/games/*`, `/playstudy-sdk.js`, `/sw.js`
  - `s3:PutObject` from `logging.s3.amazonaws.com` on `/access-logs/*`
- **CORS:** `GET`, `HEAD` from any origin (mobile + web iframe)
- **Server access logging:** ON → `s3://playstudy-games-prod/access-logs/`

### IAM / account

| | Status |
|---|---|
| Root account MFA | ✅ Enabled |
| IAM password policy | ✅ 14 chars, complexity, 90-day rotation, no-reuse-5 |
| CloudTrail | ❌ None (was broken since May; deleted; recreate when team grows) |
| GuardDuty | ❌ Off (consider free-trial when ready) |
| AWS Config | ❌ Off |

### Nothing else exists
RDS, Lambda, ECS, ECR (besides CDK bootstrap), CloudFront, WAF, ALB, Cognito,
Secrets Manager, Route 53, ACM are all **empty**.

---

## Backend stack (docker-compose on the EC2)

`docker-compose.yml` orchestrates 5 services on one host:

| Service | Image | Memory cap | Exposed externally |
|---|---|---|---|
| `caddy` | `caddy:2-alpine` | 128 M | 80, 443 |
| `web` | built from `Dockerfile` (Python 3.12-slim + gunicorn) | 700 M | no |
| `worker` | same image as `web` | 500 M | no |
| `postgres` | `postgres:16-alpine` | 512 M | no |
| `redis` | `redis:7-alpine` | 160 M | no |

Container hardening (all services):
- `security_opt: no-new-privileges:true`
- `restart: always`
- Healthchecks where supported
- Memory limits prevent OOM cascade
- Non-root user inside the Django container (`app`)

Networking: all services on the default Compose bridge network. Only `caddy`
publishes ports to the host. Other containers reach each other by service
name (`postgres`, `redis`, `web`).

Volumes (Docker named, on EBS):
- `postgres_data` → `/var/lib/postgresql/data` (durable user data)
- `django_media` → `/app/media` + Caddy `/srv/media` (file uploads)
- `django_static` → `/app/staticfiles` + Caddy `/srv/static` (collectstatic output)
- `caddy_data`, `caddy_config` (TLS cert storage, ready when we flip on HTTPS)

### Caddy (reverse proxy)

`Caddyfile` currently in **HTTP-only mode** on `:80` (`auto_https off`).
Security headers applied to every response:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: same-origin`
- `Permissions-Policy: geolocation=(), microphone=(), camera=()`
- `Server` and `X-Powered-By` stripped

Two paths bypass the Django app (served as static files):
- `/static/*` → collectstatic output
- `/media/*` → uploaded user media

Everything else → `reverse_proxy web:8000` with `X-Forwarded-Proto` /
`X-Real-IP` headers passed through.

### Switching to HTTPS (one-line flip whenever you want)

**Option A — sslip.io (no domain, real Let's Encrypt cert):**
In `Caddyfile`, swap `:80 {` for `100-55-196-80.sslip.io {`, remove
`auto_https off`, uncomment `email`. Set `CADDY_EMAIL` in `.env.prod`. Caddy
fetches the cert in ~30 s.

**Option B — your own domain:**
1. Cloudflare DNS A record `api.playstudy.ai` → `100.55.196.80` (gray cloud)
2. In `.env.prod`: `API_DOMAIN=api.playstudy.ai`, `CADDY_EMAIL=…`,
   `ALLOWED_HOSTS=api.playstudy.ai`, `CSRF_TRUSTED_ORIGINS=https://api.playstudy.ai`,
   flip `SECURE_SSL_REDIRECT=True`, both `*_COOKIE_SECURE=True`,
   `SECURE_HSTS_SECONDS=31536000`
3. In `Caddyfile`: same swap as Option A but use `{$API_DOMAIN}` instead
4. `bash deploy/deploy.sh`

### Django

- **Settings module in prod:** `config.settings.prod`
- **Database:** Postgres 16 via `DATABASE_URL` (dj-database-url)
- **Cache + Celery broker:** Redis 7
- **Hardened transport** (env-driven for HTTP/HTTPS flexibility):
  `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`,
  `SECURE_HSTS_SECONDS` all configurable via env
- **CSRF_TRUSTED_ORIGINS:** env-driven (currently `http://100.55.196.80`)
- **Throttling** (DRF): `user=1000/day`, `anon=60/hour`, `auth=10/min`,
  `generation=10/hour`, `rewards=120/hour`
- **JWT:** SimpleJWT, HS256, access 30 min / refresh 30 days, rotated + blacklisted

---

## Database (Postgres)

**Where it lives:** a container on the EC2, data persisted in Docker named
volume `postgres_data` → physically on the 30 GB EBS root volume.

**Connection (internal):** `postgres://playstudy:PASS@postgres:5432/playstudy`
inside the Compose network. **Port 5432 is not exposed externally.**

### Schema management
- Never write SQL by hand. Use Django models + migrations.
- Local dev: `python manage.py makemigrations` → creates the migration file
- On deploy: `deploy.sh` runs `python manage.py migrate` (idempotent)
- Tracking: `django_migrations` table

### Operator commands (run on the EC2)
```bash
cd /opt/playstudy/ps-bk-dj

# psql shell
docker compose exec postgres psql -U playstudy -d playstudy

# Django dbshell (auto-uses DATABASE_URL)
docker compose exec web python manage.py dbshell

# Django shell (ORM)
docker compose exec web python manage.py shell

# Migration status
docker compose exec web python manage.py showmigrations
```

### Persistence + failure modes

| Scenario | Data state |
|---|---|
| Container restart / `compose restart` | ✅ Survives (volume persists) |
| `docker compose down` | ✅ Survives |
| `docker compose down -v` (`-v` = remove volumes) | ❌ **Wiped** |
| EC2 reboot | ✅ Survives |
| EC2 instance terminated | ❌ **Wiped** (root EBS deleted with instance) |
| EBS volume corruption / AZ failure | ❌ **Wiped** |
| `deploy.sh` redeploy | ✅ Survives |

### ⚠️ No backups configured (highest-priority gap)
Single-box, no replication, no snapshots. Loss of the EC2 = total data loss.
See **Roadmap → DB backups** for the cheap fix.

---

## Games hosting

Static web bundles in `games_host/games/` are uploaded to S3 and served
publicly. Manifest rows in Postgres tell the mobile app which games are live.

### Current setup (Path A — minimal)
- Bucket `playstudy-games-prod`, public read on `/games/*` and the SDK
- **No CloudFront** — direct S3 URLs
- `GAMES_BASE_URL=https://playstudy-games-prod.s3.amazonaws.com` (set in `.env.prod` on the box so `publish_game` can HEAD-verify bundles)
- **No GitHub OIDC** — `games_host/deploy.sh` is run **manually from a laptop**
  with `aws` CLI configured

### Publishing flow
```bash
# from your laptop (in repo root):
GAMES_BUCKET=playstudy-games-prod \
GAMES_BASE_URL=https://playstudy-games-prod.s3.amazonaws.com \
./games_host/deploy.sh
```

This script (see `games_host/deploy.sh`):
1. Generates `bundle.json` for every bundle (`tools/gen-bundle-json.mjs`)
2. `aws s3 sync games_host/games/ s3://$GAMES_BUCKET/games/` with `cache-control: immutable`
3. Uploads `playstudy-sdk.js` (short cache) and `sw.js` (no-cache)
4. Runs `python manage.py publish_game apps/games/examples/*.json` which
   HEAD-verifies each bundle is live before flipping its `enabled` row in DB

### Adding a new game (zero code change to app/backend)
1. Create `games_host/games/<slug>/<version>/index.html` (+ assets) using the SDK
2. Test in a browser: `games_host/games/<slug>/<version>/index.html?quiz=<base64>`
3. Add `apps/games/examples/<key>.json` (manifest)
4. Commit, push
5. Run the publish command above

### Updating an existing game
- Copy `games/<slug>/<v>/` → `games/<slug>/<v+1>/`, edit
- Bump `"version"` in the manifest JSON
- Republish — immutable versioned paths mean rollback = bump version back

### Killing a bad game instantly
- Edit the manifest: `"enabled": false`, commit/push, re-run publish.
  No bundle deletion needed — manifest gates visibility.

### Path B (full CloudFront/OIDC/custom-domain) — deferred
See `DEPLOY.md` for the full spec. Worth doing when: traffic grows, you want
pretty URLs (`games.playstudy.ai`), or you want CI-driven publishes.

---

## Secrets management

**Currently:** plaintext `.env.prod` file on the EC2 box, loaded by docker
compose via `env_file: .env.prod`. Never committed to git
(`.gitignore` covers it; `.dockerignore` excludes it from the image).

What's in `.env.prod`:
- `SECRET_KEY`, `JWT_SIGNING_KEY` (generated random)
- `POSTGRES_USER/PASSWORD/DB` (long random password)
- `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`
- `ANTHROPIC_API_KEY` (real key for LLM generation)
- `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` (= IP today)
- HTTP-mode flags: `SECURE_SSL_REDIRECT=False`, both `*_COOKIE_SECURE=False`, `SECURE_HSTS_SECONDS=0`
- Empty placeholders for: `GAMES_BASE_URL`, `AWS_STORAGE_BUCKET_NAME`,
  `GOOGLE_OAUTH_CLIENT_IDS`, `APPLE_BUNDLE_IDS`, `SENTRY_DSN`

`.env.prod.example` in the repo is the template — never has real secrets.

**Upgrade path:** AWS Secrets Manager + a small fetcher in `deploy.sh` —
~$0.40 per secret per month, central rotation. Worth doing when team grows.

---

## Deployment

### First-ever deploy (manual bootstrap)
Done once on a fresh box. **Currently still pending** — see `DEPLOY-TODO`
items below.

```bash
# from your laptop
ssh -i ~/.ssh/playstudy-deploy.pem ubuntu@100.55.196.80

# on the box (as ubuntu)
curl -fsSL https://raw.githubusercontent.com/Ifthikar20/ps-bk-dj/main/deploy/ec2-bootstrap.sh -o /tmp/bootstrap.sh
sudo bash /tmp/bootstrap.sh
exit
# re-ssh so the docker group sticks
ssh -i ~/.ssh/playstudy-deploy.pem ubuntu@100.55.196.80
cd /opt/playstudy/ps-bk-dj
cp .env.prod.example .env.prod
nano .env.prod                 # fill SECRET_KEY, JWT, POSTGRES_PASSWORD, ANTHROPIC_API_KEY, GAMES_BASE_URL
bash deploy/deploy.sh          # first build ~5 min, then up
```

`ec2-bootstrap.sh` applies (idempotent):
- `apt upgrade` + base packages
- 2 GB swap (`vm.swappiness=10`)
- Docker engine + compose plugin
- UFW default-deny inbound, allow 22/80/443
- SSH hardening (`/etc/ssh/sshd_config.d/99-hardening.conf`): no password,
  no root, no fwding, MaxAuthTries=3, AllowUsers=ubuntu
- fail2ban (5 fails/10m → 1h ban on SSH)
- unattended-upgrades (nightly security patches)
- Clone the repo to `/opt/playstudy/ps-bk-dj`

### Subsequent deploys (CI auto-deploy)
`.github/workflows/deploy-backend.yml` runs on push to `main`:
1. Install the CI SSH key from `SSH_PRIVATE_KEY` secret
2. SSH to `EC2_HOST` as `ubuntu`
3. Run `cd /opt/playstudy/ps-bk-dj && bash deploy/deploy.sh`

`deploy.sh` itself:
1. `git pull --ff-only`
2. `docker compose build web`
3. `docker compose up -d postgres redis`
4. `docker compose run --rm web python manage.py migrate --noinput`
5. `docker compose run --rm web python manage.py collectstatic --noinput`
6. `docker compose up -d --no-deps web worker caddy`

**Ignored paths** (don't trigger backend deploy):
- `*.md`
- `games_host/**`
- `apps/games/examples/**`
- `.github/workflows/publish-games.yml`

### Required GitHub repo secrets
| Secret | Value |
|---|---|
| `SSH_PRIVATE_KEY` | contents of `~/.ssh/playstudy-ci-deploy-v2` (the v2 key — v1 was compromised) |
| `EC2_HOST` | `100.55.196.80` |

Optional: `EC2_USER` (default `ubuntu`), `EC2_SSH_PORT` (default 22), `EC2_HOST_KEY` (pinned host key).

### Required EC2 setup for CI
The CI public key must be in the box's `~ubuntu/.ssh/authorized_keys`:
```bash
ssh -i ~/.ssh/playstudy-deploy.pem ubuntu@100.55.196.80 \
  "echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILyg7psTecX7aaXcYtVB2dZRp5Xa3ya+WWZ021sY2Aer playstudy-ci-deploy-v2' >> ~/.ssh/authorized_keys"
```

---

## Operating the box

```bash
ssh -i ~/.ssh/playstudy-deploy.pem ubuntu@100.55.196.80
cd /opt/playstudy/ps-bk-dj

# status of everything
docker compose ps

# tail logs (everything or one service)
docker compose logs -f --tail=100
docker compose logs -f web
docker compose logs -f caddy

# restart one service
docker compose restart web

# full restart preserving data
docker compose down && docker compose up -d

# WARNING: --volumes will wipe the DB
# docker compose down --volumes      # do NOT run unless intentional

# manual migration
docker compose exec web python manage.py migrate

# Django shell
docker compose exec web python manage.py shell

# psql shell
docker compose exec postgres psql -U playstudy -d playstudy

# system resources
htop                    # may need: sudo apt install htop
docker stats
df -h
free -h
```

### Common gotchas
- After editing `.env.prod`, you must `bash deploy/deploy.sh` (or at minimum
  `docker compose --env-file .env.prod up -d --force-recreate`) — env file
  is only read at container start.
- After editing `Caddyfile`, `docker compose restart caddy` is enough.
- Caddy auto-HTTPS will not work until you have a real domain or sslip.io
  hostname in the site block.
- iOS won't talk to plain HTTP unless you add an ATS exception in `Info.plist`.

---

## Mobile / web client config

| Build flag | Value (today) |
|---|---|
| `--dart-define=API_BASE_URL` | `http://100.55.196.80` |
| `--dart-define=GAMES_BASE_URL` | `https://playstudy-games-prod.s3.amazonaws.com` |

```bash
flutter run \
  --dart-define=API_BASE_URL=http://100.55.196.80 \
  --dart-define=GAMES_BASE_URL=https://playstudy-games-prod.s3.amazonaws.com
```

iOS: add ATS exception for `100.55.196.80` in `Info.plist`
(`NSExceptionAllowsInsecureHTTPLoads = true` for that domain) until HTTPS
is enabled.

---

## Security posture

### What's done ✅
- **Network**: UFW default-deny inbound, only 22/80/443
- **SSH**: ed25519 keys only, no password, no root, no fwding, MaxAuthTries=3,
  `AllowUsers=ubuntu`, fail2ban (5 fails/10m → 1h ban)
- **OS**: unattended-upgrades for nightly security patches
- **Containers**: `no-new-privileges`, memory limits, non-root user in Django image
- **HTTP headers**: X-Content-Type-Options, X-Frame-Options, Referrer-Policy,
  Permissions-Policy, server-version stripped
- **Django**: DEBUG=False, ALLOWED_HOSTS locked, CSRF_TRUSTED_ORIGINS set,
  DRF throttling, JWT rotation+blacklist
- **AWS account**: root MFA on, strong IAM password policy
- **S3**: private by default, narrowly-scoped public-read bucket policy,
  versioning on, server access logging on
- **CI/CD**: separate CI SSH key (v2; v1 rotated after exposure), Dependabot
  weekly for Python + Docker + Actions

### Open gaps (severity tag)
- 🔴 **HTTP only** — passwords/JWTs in plaintext on the wire.
  Mitigation: flip to sslip.io HTTPS (one-line Caddyfile change).
- 🔴 **No DB backups** — single point of failure for all user data.
  Mitigation: pg_dump → S3 cron (see Roadmap).
- 🟠 **AWS root account in daily use** — least-privilege violation.
  Mitigation: create IAM user for `aws` CLI, lock root.
- 🟠 **SSH world-open** (needed for GH Actions) — relies on key+fail2ban.
  Acceptable for now; tighter option later via self-hosted runner or SSM Session Manager.
- 🟡 **No CloudTrail** — no audit log of AWS API calls.
  Recreate properly when team grows or compliance matters.
- 🟡 **No monitoring/alerting** — outages noticed by users, not by us.
  Mitigation: CloudWatch alarm on EIP unreachability + UptimeRobot-style external check.
- 🟡 **No Sentry** — errors visible only in container logs.
  Already wired in `prod.py` — just set `SENTRY_DSN` in `.env.prod` when you have an account.
- 🟡 **No GuardDuty** — no automated threat detection.
- 🟢 **No social auth keys set** — Google/Apple sign-in will 400 until configured.
  Required for shipping iOS.

---

## Cost breakdown

| Item | $/month |
|---|---|
| EC2 `t3.small` (730 hrs) | ~$15.18 |
| EBS 30 GB gp3 | ~$2.40 |
| Elastic IP (attached) | ~$3.60 |
| S3 (games bucket, near-empty) | ~$0.05 |
| ECR (CDK bootstrap only) | ~$0.16 |
| Tax | ~$2 |
| **Total — playstudy only** | **~$23/mo** |
| (fetchbot-prod, separate project) | ~$20/mo |

For context: account was at **~$117/mo in May 2026**. Now ~$43/mo total
(playstudy + fetchbot), a 63% reduction, *and* we have a working production
backend instead of a dead BetterBliss stack.

---

## Roadmap (deferred items, ordered by ROI)

| # | Item | Effort | Cost | Why |
|---|---|---|---|---|
| 1 | **HTTPS via sslip.io** (Caddyfile one-line flip) | 2 min | $0 | Stops plaintext credentials |
| 2 | **DB backups**: nightly pg_dump → S3 + lifecycle delete >30d | 30 min | ~$0.05/mo | Stops total data loss on EC2 failure |
| 3 | **Sentry DSN** — already wired, just sign up + paste | 5 min | $0 (free tier) | Real error visibility |
| 4 | **Non-root IAM user** for daily `aws` CLI | 10 min | $0 | Least privilege |
| 5 | **CloudWatch alarm** on EC2 status check fail + EIP unreachability + SNS email | 15 min | ~$0.30/mo | Know about outages before users do |
| 6 | **External uptime check** (UptimeRobot free / Better Stack free) hitting `/health/` every 5 min | 5 min | $0 | Catches network-level outages CloudWatch misses |
| 7 | **GuardDuty** | 5 min | ~$3–5/mo after 30d trial | Threat detection on EC2 + S3 |
| 8 | **CloudTrail** to a new logs bucket | 10 min | <$1/mo | Audit trail of AWS API calls |
| 9 | **Custom domain** `api.playstudy.ai` + `games.playstudy.ai` | 20 min | $0 (Cloudflare DNS) | Proper TLS, pretty URLs, no IP-in-app-config |
| 10 | **CloudFront in front of games S3** | 30 min | $0 first year (free tier) | Edge caching, custom domain on games |
| 11 | **GitHub OIDC role for game publishes via CI** | 20 min | $0 | Removes manual laptop deploys for games; no long-lived keys |
| 12 | **S3 bucket for user media uploads** (`AWS_STORAGE_BUCKET_NAME`) | 15 min | ~$0.05/mo + traffic | Today uploads go to EC2 disk; lost if instance dies |
| 13 | **Google + Apple social auth keys** | depends | $0 (Apple Dev costs separate) | Required before App Store submission |
| 14 | **Secrets Manager** for prod secrets | 30 min | ~$0.40/secret/mo | Central rotation, audit log |
| 15 | **RDS + ElastiCache** (split DB/Redis off the box) | 1–2 hrs | +$30–40/mo | When single-box ceases to be acceptable risk |

Items 1, 2, 3 are the no-brainer next batch — high ROI, low effort, low cost.

---

## DEPLOY-TODO — manual steps still pending

The infra is provisioned but the box hasn't booted up yet. To go live:

1. `git push` the scaffolded files (this doc, Dockerfile, compose, Caddyfile, dependabot, etc.)
2. SSH in + run `ec2-bootstrap.sh` (5 min)
3. Create `.env.prod` on the box (3 min) — paste the generated SECRET_KEY/JWT_SIGNING_KEY/POSTGRES_PASSWORD + add ANTHROPIC_API_KEY + set `GAMES_BASE_URL`
4. First deploy: `bash deploy/deploy.sh` (5 min for the initial image build)
5. Add CI key to box `authorized_keys` (one-liner above)
6. Add `SSH_PRIVATE_KEY` + `EC2_HOST` GitHub repo secrets
7. Smoke test: `curl http://100.55.196.80/health/`
8. Publish first games batch: `GAMES_BUCKET=playstudy-games-prod ./games_host/deploy.sh`
9. Point mobile build: `flutter run --dart-define=API_BASE_URL=http://100.55.196.80 --dart-define=GAMES_BASE_URL=https://playstudy-games-prod.s3.amazonaws.com`

---

## Quick reference

| | |
|---|---|
| **API** | http://100.55.196.80 |
| **API health** | http://100.55.196.80/health/ |
| **Django admin** | http://100.55.196.80/admin/ |
| **Games CDN** | https://playstudy-games-prod.s3.amazonaws.com |
| **EC2 IP** | 100.55.196.80 |
| **EC2 SSH** | `ssh -i ~/.ssh/playstudy-deploy.pem ubuntu@100.55.196.80` |
| **AWS account** | 817977750104 (us-east-1) |
| **GitHub repo** | https://github.com/Ifthikar20/ps-bk-dj |
| **GH Actions** | https://github.com/Ifthikar20/ps-bk-dj/actions |
| **Backend deploy workflow** | `.github/workflows/deploy-backend.yml` |
| **Games publish workflow** | `.github/workflows/publish-games.yml` (defined; needs OIDC to actually run) |
| **Bootstrap script** | `deploy/ec2-bootstrap.sh` |
| **Deploy script** | `deploy/deploy.sh` |
