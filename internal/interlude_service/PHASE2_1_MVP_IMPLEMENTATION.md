# Phase 2.1: MVP Cloud Deployment & Go-to-Market

> **Date**: 2026-03-29
> **Depends on**: Phase 1 (auth, API, monitoring) + Phase 2 (what-if, export, billing wiring)
> **Goal**: Take the localhost demo online so leads from marketing outreach become users and then customers.

---

## Current State

| Component | Where it runs | How |
|---|---|---|
| Go frontend (:8080) | Docker on localhost | `main/Dockerfile` → distroless container |
| ML service (:8000) | Docker on localhost | `machinelearning/Dockerfile` → python:3.11-slim + PyTorch CPU |
| Caddy reverse proxy (:80/:443) | Docker on localhost | Caddy 2 with auto-TLS |
| PostgreSQL (:5432) | Host machine directly | `musicbrainz_db`, ~13 tables, accessed via `host.docker.internal` |
| ML models | Baked into ML container | ~1.2 MB total (988K PyTorch, 4x logit <32K each) |
| Demo page | Served at `/demo` by Go | `templates/demo.html` + `static/demo.js` |
| Daily page | Served at `/daily` by Go | `templates/daily.html` — Spotle integration |

**No cloud infrastructure exists** — no Terraform, no Kubernetes, no managed services.

---

## 1. Database: Where and How to Host in the Cloud

### Recommendation: **AWS RDS PostgreSQL** (or Supabase as fast alternative)

| Option | Pros | Cons | Cost |
|---|---|---|---|
| **AWS RDS PostgreSQL** (recommended) | Managed backups, read replicas, IAM auth, connection pooling via RDS Proxy | AWS complexity, cold start on small instances | db.t4g.micro free tier 12mo, then ~$15/mo |
| **Supabase** (fast MVP alternative) | Free tier (500MB), built-in auth, instant setup, PostgREST API | 500MB limit on free tier, less control | Free → $25/mo Pro |
| **Railway** | One-click Postgres, simple deploy | Smaller ecosystem, less mature | $5/mo + usage |
| **Self-hosted on EC2/Droplet** | Full control | You manage backups, security, patching | $5-20/mo |

### Migration steps

```
1. Provision RDS instance (or Supabase project)
   - Engine: PostgreSQL 16
   - Instance: db.t4g.micro (MVP) → db.t4g.small (production)
   - Storage: 20 GB gp3 (plenty for current data)
   - Enable SSL/TLS connections
   - Set up security group: only allow inbound from app servers

2. Export local database
   pg_dump -U postgres -d musicbrainz_db \
     --no-owner --no-acl \
     -F custom -f musicbrainz_db.dump

3. Import to cloud
   pg_restore -h YOUR_RDS_ENDPOINT -U postgres -d musicbrainz_db \
     --no-owner musicbrainz_db.dump

4. Run Phase 1 migration on cloud DB
   psql -h YOUR_RDS_ENDPOINT -U postgres -d musicbrainz_db \
     -f internal/interlude_service/machinelearning/migrations/001_phase1_tables.sql

5. Update connection strings
   - Replace host.docker.internal:5432 with RDS endpoint
   - Enable sslmode=require
   - Store credentials in AWS Secrets Manager (not .env files)
```

### Data size estimate

| Table | Estimated rows | Size |
|---|---|---|
| artist | ~580K | ~100 MB |
| artist_collab | ~2M edges | ~200 MB |
| artist_embeddings_n2v (128-dim) | ~580K | ~600 MB |
| prediction_connections | grows with usage | ~50 MB initial |
| synthetic_tracks + features | grows with usage | ~20 MB initial |
| Everything else | — | ~200 MB |

**Total: ~1.2 GB** — well within RDS free tier (20 GB) and Supabase Pro (8 GB).

---

## 2. Endpoints: Where and How to Host the API

### Recommendation: **AWS ECS Fargate** (or Railway/Render for fast MVP)

The app is already containerized (docker-compose with 3 services), so the migration is straightforward.

| Option | Pros | Cons | Cost |
|---|---|---|---|
| **AWS ECS Fargate** (recommended) | Serverless containers, auto-scaling, ALB integration, IAM | More setup, AWS learning curve | ~$30-50/mo for 2 services |
| **Railway** (fastest MVP) | Git push to deploy, docker-compose support, built-in domains | Less control, scaling limits | ~$20-40/mo |
| **Render** | Simple Docker deploy, free TLS, managed Postgres add-on | Cold starts on free tier, limited scaling | $7/mo per service |
| **DigitalOcean App Platform** | Docker support, managed DB add-on, simple | Less mature than AWS | $12/mo per service |
| **AWS EC2 + Docker Compose** | Cheapest, most familiar workflow | You manage everything | $10-20/mo (t3.small) |

### Architecture for ECS Fargate

```
Internet
  │
  ▼
┌──────────────────┐
│  AWS ALB          │  ← TLS termination (ACM cert for your domain)
│  (load balancer)  │  ← Rate limiting via WAF (optional)
└────┬─────────┬───┘
     │         │
     │ /api/*  │  /*
     │ /docs   │
     │ /metrics│
     ▼         ▼
┌─────────┐  ┌─────────┐
│ ML Svc  │  │ Go API  │
│ (Fargate│  │ (Fargate│
│  Task)  │  │  Task)  │
│ :8000   │  │ :8080   │
└────┬────┘  └────┬────┘
     │            │
     ▼            ▼
┌──────────────────┐
│  RDS PostgreSQL   │
│  (private subnet) │
└──────────────────┘
```

### Migration steps

```
1. Push Docker images to ECR (AWS Container Registry)
   aws ecr create-repository --repository-name melodymap-ml
   aws ecr create-repository --repository-name melodymap-api

   docker build -t melodymap-ml ./internal/interlude_service/machinelearning
   docker build -t melodymap-api -f main/Dockerfile .

   docker tag melodymap-ml:latest <account>.dkr.ecr.<region>.amazonaws.com/melodymap-ml:latest
   docker tag melodymap-api:latest <account>.dkr.ecr.<region>.amazonaws.com/melodymap-api:latest

   docker push <account>.dkr.ecr.<region>.amazonaws.com/melodymap-ml:latest
   docker push <account>.dkr.ecr.<region>.amazonaws.com/melodymap-api:latest

2. Create ECS cluster + task definitions
   - ML service: 1 vCPU, 2 GB RAM (PyTorch needs memory)
   - Go API: 0.25 vCPU, 0.5 GB RAM (Go is lightweight)
   - Both use awsvpc networking in private subnets

3. Create ALB with target groups
   - /api/v1/*, /docs, /redoc, /metrics, /ml/*, /interlude/* → ML service
   - /* → Go API
   - Health checks: /api/v1/health for ML, / for Go

4. Configure environment variables via Secrets Manager
   - PG_DSN (with RDS endpoint)
   - INTERNAL_SERVICE_SECRET
   - LASTFM_API_KEY, LASTFM_API_SECRET
   - SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
   - STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET

5. Domain + TLS
   - Point your domain (e.g. api.interlude.fm) to ALB
   - ACM certificate (free, auto-renewing)
   - Caddy is no longer needed — ALB handles TLS
```

### Quick MVP alternative: Railway

If AWS is too much setup for the MVP demo:

```
1. Create Railway project
2. Add PostgreSQL service (Railway provides managed Postgres)
3. Add service from Dockerfile: internal/interlude_service/machinelearning/
4. Add service from Dockerfile: main/
5. Set environment variables in Railway dashboard
6. Railway auto-assigns HTTPS domains (e.g. melodymap-ml.up.railway.app)
7. Point custom domain via CNAME
```

Railway supports docker-compose-like multi-service projects and costs ~$5/mo per service with usage billing. This can be up and running in under an hour.

---

## 3. Demo Page: Where and How to Host

### Current state

The demo page (`templates/demo.html` + `static/demo.js`) is served by the Go frontend at `/demo`. It calls the ML service's `/api/v1/*` endpoints for predictions.

### Recommendation: **Keep it bundled with the Go frontend**

The demo page doesn't need separate hosting — it's a static HTML/JS page served by the same Go container. When the Go service goes to ECS/Railway, the demo page goes with it automatically.

**What needs to change for production:**

```
1. Update demo.js API base URL
   - Currently: relative paths (e.g. /api/v1/predict/connection)
   - These work as-is when Go proxies to ML service
   - For direct API access: set base URL to your domain

2. Remove --reload flag from ML Dockerfile
   - Current: CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
   - Production: CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
   - Multiple workers handle concurrent demo users

3. Add CORS headers if demo is on a different domain than API
   - If demo at interlude.fm and API at api.interlude.fm:
     Add CORS middleware to FastAPI app.py

4. Pre-seed demo predictions
   - Run /api/v1/internal/populate-daily on deploy
   - Pre-compute predictions for popular artists (Beatles, Drake, Taylor Swift, etc.)
   - This ensures the demo feels instant, not "loading for 30 seconds"
```

### Pages to expose publicly

| Page | URL | Purpose | Target audience |
|---|---|---|---|
| Demo | `/demo` | Interactive API demo — try predictions | Leads from email outreach |
| Daily | `/daily` | Genre-based daily discovery + Spotify playlists | Casual users, Spotle players |
| ML Dashboard | `/ml` | Full analytics — connections, predictions, tables | Power users, researchers |
| API Docs | `/docs` | Swagger UI — self-service API exploration | Developers |
| Combined | `/` | Main dashboard with graph + ML + playlists | Everyone |

---

## 4. Other Migrations and Hosting Considerations

### 4.1 Secrets Management

| Secret | Current location | Cloud location |
|---|---|---|
| PG_DSN (DB password) | `.env.docker` (plaintext) | AWS Secrets Manager / Railway env vars |
| SPOTIFY_CLIENT_ID/SECRET | `.env.docker` | Secrets Manager |
| LASTFM_API_KEY/SECRET | `.env.docker` | Secrets Manager |
| INTERNAL_SERVICE_SECRET | `.env.docker` | Secrets Manager |
| STRIPE_SECRET_KEY | env var in Go | Secrets Manager |
| STRIPE_WEBHOOK_SECRET | env var in Go | Secrets Manager |

**Action**: No more `.env` files in production. All secrets injected via cloud provider's secrets management.

### 4.2 Domain & DNS

```
interlude.fm (or your chosen domain)
  │
  ├── interlude.fm/           → Go frontend (combined dashboard)
  ├── interlude.fm/demo       → Demo page (leads land here)
  ├── interlude.fm/daily      → Daily discovery page
  ├── interlude.fm/ml         → ML analytics dashboard
  ├── interlude.fm/docs       → Swagger API docs
  └── interlude.fm/api/v1/*   → ML service API endpoints
```

Single domain, single ALB/reverse proxy. No need for subdomains initially.

### 4.3 ML Dockerfile Production Changes

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

# Production: no --reload, 2 workers, timeout for long predictions
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--timeout-keep-alive", "120"]
```

### 4.4 Monitoring in Production

Phase 1 already added Prometheus metrics at `/metrics`. In the cloud:

| Option | Setup | Cost |
|---|---|---|
| **Grafana Cloud** (recommended) | Free tier: 10K metrics, 50 GB logs. Scrape `/metrics` endpoint. | Free |
| **AWS CloudWatch** | Built-in for ECS. Container insights for CPU/memory. | ~$3/mo |
| **Datadog** | Agent-based, great dashboards. | $15/mo per host |

Minimal viable monitoring:
1. Grafana Cloud free tier scraping `/metrics`
2. CloudWatch alarms on ECS task health
3. Uptime check on `/api/v1/health` (UptimeRobot, free)

### 4.5 CI/CD Pipeline

```
GitHub Actions (free for public repos, 2000 min/mo for private):

on push to main:
  1. Build Docker images
  2. Push to ECR
  3. Update ECS service (rolling deploy)
  4. Run smoke test: curl /api/v1/health
```

### 4.6 Backup Strategy

| Data | Backup method | Frequency |
|---|---|---|
| RDS PostgreSQL | Automated snapshots | Daily (RDS default, 7-day retention) |
| Model files (1.2 MB) | Stored in Git + Docker image | Every deploy |
| User data (api_users, feedback) | RDS snapshots | Daily |

---

## 5. Marketing Emails → MVP Feature Mapping

From `marketing-emails.md`, the key insight is:

> "Your product answers 'What collaborations are likely?' but customers care about 'What collaborations will MAKE MONEY?'"

The MVP doesn't need to solve the full "hit prediction" problem yet. It needs to **demonstrate enough value to convert leads into pilot deals**. Here's what the demo must show:

### What leads need to see (from marketing outreach)

| Lead type | What they click | What convinces them | MVP feature needed |
|---|---|---|---|
| **A&R / indie label** | Demo page link in email | "Top predicted collaborations" ranked list with names they recognize | Pre-computed neighbor predictions for popular artists, displayed on `/demo` |
| **Music data scientist** | API docs link | Working API with auth, versioning, batch support | Already built (Phase 1+2) — `/docs` page |
| **Creator platform (Suno, BandLab)** | Demo page + API docs | CVAE conditioning outputs that could plug into generation | What-if endpoint + synthetic track features (Phase 2) |
| **Hedge fund / alt-data** | Export endpoint | Downloadable dataset with prediction probabilities | Export endpoint (Phase 2) |

### Lead → User → Customer funnel

```
1. LEAD (from email outreach)
   → lands on interlude.fm/demo
   → tries a prediction (no signup needed — use demo API key)
   → sees probability + synthetic tracks + similar real tracks

2. USER (registers for free tier)
   → POST /api/v1/auth/register
   → gets API key, 100 requests/hour
   → explores /docs, runs batch predictions
   → hits rate limit → sees upgrade prompt

3. CUSTOMER (paid tier)
   → Stripe checkout (already wired in Phase 2)
   → researcher ($49/mo) or enterprise ($299/mo)
   → batch predictions, dataset exports, model comparison

4. ENTERPRISE (pilot deal)
   → Direct outreach from usage data
   → Custom model training, dataset licensing
   → $5K-$50K contracts
```

### Pre-seed data for the demo

The demo must feel instant. Before launch, run:

```bash
# Pre-compute predictions for ~50 well-known artists
# so the demo always has cached results ready
curl -X POST https://interlude.fm/api/v1/predict/neighbors \
  -H "X-Internal-Secret: $SECRET" \
  -H "Content-Type: application/json" \
  -d '{"artist": "Drake", "limit": 20}'

# Repeat for: Taylor Swift, Kendrick Lamar, Radiohead, Billie Eilish,
# The Weeknd, Bad Bunny, Dua Lipa, Tyler the Creator, SZA, etc.

# Pre-compute what-if scenarios for interesting pairs
curl -X POST https://interlude.fm/api/v1/explore/what-if \
  -H "X-Internal-Secret: $SECRET" \
  -H "Content-Type: application/json" \
  -d '{"artists": ["Radiohead", "Kendrick Lamar"]}'

# Populate daily predictions
curl -X POST https://interlude.fm/api/v1/internal/populate-daily \
  -H "X-Internal-Secret: $SECRET"
```

---

## 6. Cost Summary (MVP)

### Option A: AWS (production-ready)

| Service | Monthly cost |
|---|---|
| RDS PostgreSQL (db.t4g.micro) | $0 (free tier 12 mo) → $15/mo |
| ECS Fargate (ML service: 1 vCPU, 2 GB) | ~$30/mo |
| ECS Fargate (Go API: 0.25 vCPU, 0.5 GB) | ~$8/mo |
| ALB | ~$16/mo + $0.008/LCU-hr |
| ECR (container registry) | ~$1/mo |
| Secrets Manager | ~$2/mo |
| Domain (Route 53) | $12/year |
| **Total** | **~$60-75/mo** |

### Option B: Railway (fastest to launch)

| Service | Monthly cost |
|---|---|
| PostgreSQL | $5/mo + usage |
| ML service | ~$10-20/mo |
| Go API | ~$5-10/mo |
| Domain (external) | $12/year |
| **Total** | **~$20-35/mo** |

### Option C: Single EC2 + Docker Compose (cheapest)

| Service | Monthly cost |
|---|---|
| EC2 t3.small (2 vCPU, 2 GB) | ~$15/mo |
| RDS free tier | $0 (12 mo) |
| Domain | $12/year |
| **Total** | **~$15-20/mo** |

**Recommendation for MVP**: Start with **Railway** (Option B) to get online in hours, not days. Migrate to AWS (Option A) when you have paying customers and need auto-scaling.

---

## 7. Implementation Checklists

### Already Done (by Claude)

These files are in the repo and ready to use:

```
[x] ML Dockerfile — production mode via RUN_ENV=production
    → machinelearning/Dockerfile: auto-switches between --reload (dev) and --workers 2 (prod)

[x] Root .dockerignore — keeps Go build context clean
    → .dockerignore: excludes .git, python envs, notebooks, secrets, data dirs

[x] Render deployment config
    → render.yaml: Blueprint for one-click deploy (2 services + PostgreSQL)
    → Provisions melodymap-api (Go), melodymap-ml (Python), melodymap-db (Postgres)
    → Auto-links database connection strings, generates internal secrets

[x] Railway deployment config
    → railway.toml: Config for Go API service
    → Includes full setup instructions for Railway monorepo (2 services + Postgres)

[x] Pre-seed script for demo data
    → scripts/preseed_demo.sh: Pre-computes predictions for 30 popular artists,
      8 what-if scenarios, and daily predictions for all 12 genres
    → Run after deploy to make the demo page feel instant

[x] docker-compose.yml — production-ready
    → PG_DSN now uses env var with local fallback (no more only-hardcoded password)
    → RUN_ENV passed through to ML service (controls dev vs prod mode)

[x] .env.example — updated with Railway/Render/production notes
    → Documents how to set PG_DSN, ML_SERVICE_URL for each platform

[x] PostgreSQL 18 compatibility verified
    → Go: pgx v5.7.6 — fully compatible
    → Python: psycopg2-binary + SQLAlchemy — fully compatible
    → No PG18-incompatible syntax found in any queries
    → Connection string prefix auto-conversion already in app.py
```

### Your Checklist (things only you can do)

```
Phase 2.1 — Cloud MVP Deployment

DATABASE
[x] Export your local database
    pg_dump -U postgres -d musicbrainz_db \
      --no-owner --no-acl -F custom -f musicbrainz_db.dump
    # Estimated size: ~1.2 GB

[ ] Pick your platform and provision PostgreSQL:

    RAILWAY:
    [ ] Install Railway CLI: npm install -g @railway/cli
    [ ] railway login
    [ ] railway init (create project)
    [ ] Add PostgreSQL service in Railway dashboard (+ New → Database → PostgreSQL)
    [ ] Import database:
        pg_restore -h <RAILWAY_PG_HOST> -p <PORT> -U postgres \
          -d railway musicbrainz_db.dump

    RENDER:
    [ ] Go to render.com → New → Blueprint
    [ ] Point to your GitHub repo — it will read render.yaml automatically
    [ ] Render provisions the database — import data:
        pg_restore -h <RENDER_PG_HOST> -p <PORT> -U postgres \
          -d musicbrainz_db musicbrainz_db.dump

[ ] Run Phase 1 migration on cloud DB:
    psql -h <CLOUD_HOST> -U postgres -d musicbrainz_db \
      -f internal/interlude_service/machinelearning/migrations/001_phase1_tables.sql

[ ] Verify with: psql -h <CLOUD_HOST> -c "SELECT count(*) FROM artist;"
    (should return ~580K rows)

DEPLOY SERVICES
[ ] Railway path:
    [ ] Add melodymap-api service (root dir: /, Dockerfile: main/Dockerfile)
    [ ] Add melodymap-ml service (root dir: internal/interlude_service/machinelearning)
    [ ] Set all env vars listed in railway.toml comments
    [ ] Key env vars:
        - PG_DSN=${{Postgres.DATABASE_URL}}
        - ML_SERVICE_URL=http://melodymap-ml.railway.internal:8000
        - RUN_ENV=production
        - INTERNAL_SERVICE_SECRET=<generate one, use same for both services>

    Render path:
    [ ] The render.yaml Blueprint handles most of this automatically
    [ ] Fill in the secrets it prompts for (Spotify, Stripe, LastFM keys)

[ ] Verify health: curl https://YOUR_DOMAIN/api/v1/health
[ ] Verify demo page: open https://YOUR_DOMAIN/demo
[ ] Verify ML page: open https://YOUR_DOMAIN/ml
[ ] Verify daily page: open https://YOUR_DOMAIN/daily
[ ] Verify homepage: open https://YOUR_DOMAIN/
[ ] Verify API docs: open https://YOUR_DOMAIN/docs

DOMAIN & TLS
[ ] Register domain (if you don't have one) or use the Railway/Render default domain
[ ] Point your domain's DNS to Railway/Render:
    - Railway: CNAME to your-app.up.railway.app
    - Render: CNAME to your-service.onrender.com
[ ] Both platforms auto-provision TLS — no manual cert setup needed
[ ] Update SPOTIFY_REDIRECT_URI to https://YOUR_DOMAIN/auth/callback
[ ] Update Stripe webhook URL to https://YOUR_DOMAIN/api/stripe/webhook

PRE-SEED DEMO DATA
[ ] After services are healthy, run the pre-seed script:
    ./scripts/preseed_demo.sh https://YOUR_DOMAIN YOUR_INTERNAL_SECRET
    # This takes 10-30 minutes (runs ML pipeline for 30 artists + 12 genres)
[ ] Verify demo loads instantly for "Drake", "Taylor Swift", etc.

MONITORING
[ ] Sign up for UptimeRobot (free) — add check for /api/v1/health
[ ] Optional: Grafana Cloud (free tier) — scrape /metrics endpoint

SPOTIFY OAUTH (for playlist features)
[ ] Go to Spotify Developer Dashboard
[ ] Add your production redirect URI: https://YOUR_DOMAIN/auth/callback
[ ] Update SPOTIFY_REDIRECT_URI env var in Railway/Render

STRIPE (for paid tiers)
[ ] Update Stripe webhook endpoint to: https://YOUR_DOMAIN/api/stripe/webhook
[ ] Update STRIPE_SUCCESS_URL and STRIPE_CANCEL_URL env vars

MARKETING
[ ] Update email templates with live demo URL
[ ] Key links to share:
    - Demo: https://YOUR_DOMAIN/demo (interactive, no signup needed)
    - API docs: https://YOUR_DOMAIN/docs (self-service for developers)
    - ML dashboard: https://YOUR_DOMAIN/ml (shows depth of the project)
    - Homepage: https://YOUR_DOMAIN/ (full graph + ML + playlists)
[ ] Test the full funnel:
    email link → /demo → try prediction → /api/v1/auth/register → get API key → /docs
```

### Cost estimate (Railway + Render)

| Component | Railway | Render |
|---|---|---|
| PostgreSQL | ~$7/mo (1 GB) | ~$7/mo (starter) |
| ML service (2 GB RAM for PyTorch) | ~$20/mo | ~$25/mo (standard) |
| Go API (512 MB RAM) | ~$5/mo | ~$7/mo (starter) |
| Custom domain | Free (CNAME) | Free (CNAME) |
| TLS certificates | Auto (free) | Auto (free) |
| **Total** | **~$32/mo** | **~$39/mo** |
