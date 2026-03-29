# Daily Predictions Scheduler

This document describes the daily predictions scheduler system that pre-computes ML predictions for all genres at 12:00 PM EST each day and serves them instantly on the `/daily` page.

## Overview

The Daily Scheduler automatically generates artist collaboration predictions for every genre at a fixed time each day. These predictions are stored in PostgreSQL and served to users immediately when they visit the `/daily` page, eliminating the need for on-demand ML service calls.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Go Server (main)                                  │
│                                                                             │
│   ┌─────────────────────┐    ┌──────────────────────────────┐              │
│   │  Daily Scheduler    │    │  HTTP Handlers               │              │
│   │  (Background)       │    │                              │              │
│   │                     │    │  GET  /api/daily/today        │              │
│   │  Fires at 12pm EST  │    │  POST /api/daily/predict      │              │
│   │  every day          │───▶│  POST /api/daily/create-playlist │           │
│   │                     │    │                              │              │
│   │  On startup: checks │    │  Serves cached predictions   │              │
│   │  for missing data   │    │  Falls back to on-demand     │              │
│   └─────────────────────┘    └──────────────────────────────┘              │
└─────────────────────────────────────────────────────────────────────────────┘
         │                              │
         ▼                              ▼
┌─────────────────────┐    ┌──────────────────────────────────┐
│  ML Service (Python) │    │  PostgreSQL                      │
│  /interlude/         │    │                                  │
│  daily-prediction    │    │  daily_predictions table         │
│                      │    │  - date, genre                   │
│  Selects random      │    │  - src_artist_id, src_artist_name│
│  artist per genre,   │    │  - response_json (JSONB)         │
│  runs ML pipeline    │    │  - UNIQUE(date, genre)           │
└──────────────────────┘    └──────────────────────────────────┘
```

## Database Schema

```sql
CREATE TABLE IF NOT EXISTS daily_predictions (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    genre TEXT NOT NULL,
    src_artist_id TEXT NOT NULL,       -- MusicBrainz MBID
    src_artist_name TEXT NOT NULL,
    response_json JSONB NOT NULL,      -- Full ML response (neighbors, tracks, etc.)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(date, genre)
);
```

The table is auto-created on server startup via `initDailyPredictionsTable()` in `main/daily_scheduler.go`.

## Supported Genres

The scheduler generates predictions for the following 12 genres:

| Genre | Tag Name |
|-------|----------|
| Rock | `rock` |
| Pop | `pop` |
| Hip Hop | `hip hop` |
| Jazz | `jazz` |
| Classical | `classical` |
| Electronic | `electronic` |
| R&B | `r&b` |
| Country | `country` |
| Metal | `metal` |
| Folk | `folk` |
| Punk | `punk` |
| Blues | `blues` |

These match the genre buttons on the `/daily` HTML page (`templates/daily.html`).

## Scheduler Behavior

### On Server Startup

1. `initDailyPredictionsTable()` creates the `daily_predictions` table if it doesn't exist
2. `startDailyScheduler()` launches a background goroutine
3. The goroutine immediately calls `generateMissingPredictions()` which:
   - Queries the database for today's date (in EST timezone)
   - Counts how many genres already have predictions
   - Generates predictions only for missing genres
   - If all 12 genres are present, no ML service calls are made

### At 12:00 PM EST Daily

1. The scheduler calculates the next 12:00 PM EST using `time.LoadLocation("America/New_York")`
2. Sleeps until that time using `time.NewTimer`
3. Calls `generateAllPredictions()` which iterates all 12 genres
4. For each genre:
   - Calls `POST /interlude/daily-prediction` on the ML service with `{ date, genre, limit: 10 }`
   - Parses the response to extract `src_artist_id` and `src_artist_name`
   - Upserts into `daily_predictions` using `ON CONFLICT (date, genre) DO UPDATE`
5. Logs progress for each genre
6. If a genre fails, logs the error and continues with the next genre

### Timezone Handling

All date calculations use **America/New_York** (EST/EDT). If the timezone database is unavailable, falls back to a fixed UTC-5 offset.

## API Endpoints

### GET /api/daily/today

Returns all pre-computed predictions for today.

**Request:**
```
GET /api/daily/today
Headers: X-SDS-Token: <token>
```

**Response (predictions available):**
```json
{
  "date": "2026-02-15",
  "ready": true,
  "genres": {
    "rock": {
      "date": "2026-02-15",
      "genre": "rock",
      "src_artist_id": "mbid-uuid",
      "src_artist_name": "Artist Name",
      "neighbors": [...],
      "model_version": "v5",
      "latency_ms": 1234.5
    },
    "pop": { ... },
    "jazz": { ... }
  }
}
```

**Response (no predictions yet):**
```json
{
  "date": "2026-02-15",
  "ready": false,
  "genres": {}
}
```

### POST /api/daily/predict (updated)

Now checks for cached predictions before calling the ML service.

**Flow:**
1. Parse request for `genre`, `date`, `limit`
2. Check `daily_predictions` table for matching `(date, genre)`
3. If found: return cached `response_json` immediately (no billing, no ML call)
4. If not found: fall back to original behavior (check billing tier, call ML service, increment usage)

## Frontend Integration

### Page Load Flow

1. `DOMContentLoaded` fires
2. `loadPrecomputedPredictions()` fetches `GET /api/daily/today`
3. If `ready: true`, stores all genre data in `DailyState.precomputed`
4. Adds `.precomputed` CSS class to genre buttons with available data (shows green dot indicator)
5. Auto-selects the first available genre and renders its predictions immediately

### Genre Button Click

1. Check `DailyState.precomputed[genre]` for cached data
2. If found: render instantly (no spinner, no API call, no billing usage)
3. If not found: fall back to `POST /api/daily/predict` (on-demand, with billing check)

### Visual Indicators

Genre buttons with pre-computed data show a small green dot (`.precomputed::after` CSS pseudo-element) and a green-tinted border.

## File Locations

| File | Purpose |
|------|---------|
| `main/daily_scheduler.go` | Scheduler goroutine, DB migration, prediction generation and storage |
| `main/daily_handlers.go` | `dailyTodayHandler`, updated `dailyPredictHandler` with cache check |
| `main/main.go` | Route registration for `/api/daily/today`, scheduler startup |
| `static/daily.js` | Frontend auto-load, precomputed cache, genre selection logic |
| `static/daily.css` | `.precomputed` button styles (green dot indicator) |
| `templates/daily.html` | Genre buttons (no changes needed) |

## Monitoring

The scheduler logs extensively to stdout with the `[daily-scheduler]` prefix:

```
[daily-scheduler] daily_predictions table ready
[daily-scheduler] Found 0/12 genres for today, generating missing ones
[daily-scheduler] Generating predictions for genre="rock" date=2026-02-15
[daily-scheduler] Stored prediction for genre="rock" artist="Led Zeppelin"
[daily-scheduler] Finished generating predictions for 2026-02-15
[daily-scheduler] Next generation at 2026-02-16T12:00:00-05:00 (sleeping 23h45m12s)
```

Cached prediction serving logs with `[daily/predict]`:

```
[daily/predict] Serving cached prediction for genre="rock" date=2026-02-15
```

## Failure Handling

- If the ML service is unavailable for a genre, that genre is skipped and the scheduler continues with the remaining genres
- On the next server restart, `generateMissingPredictions()` will attempt to fill in any gaps
- The frontend gracefully falls back to on-demand prediction if no pre-computed data exists
- Database upserts (`ON CONFLICT DO UPDATE`) make re-runs idempotent
