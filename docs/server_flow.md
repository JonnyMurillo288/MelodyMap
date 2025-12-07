# Server Flow (server.go)

This document outlines the HTTP server flow and handlers defined in `server.go`.

## Overview

The server initializes the template engine and the database store, then registers HTTP handlers for the UI and API endpoints.

## Flow Chart

```mermaid
flowchart TD
    A[Start] --> B[Initialize Template: templates/index.html]
    B --> C[Open DB Store]
    C --> D{Migrate DB?}
    D -->|Success| E[ServerMux and Routes]
    D -->|Fail| Z[log.Fatalf and Exit]

    E --> R1[GET /]
    E --> R2[GET /status]
    E --> R3[GET /auth]
    E --> R4[GET /callback]
    E --> R5[POST /search]

    R1 --> R1a{Method GET?}
    R1a -->|No| R1b[405 Method Not Allowed]
    R1a -->|Yes| R1c[Execute index.html Template]
    R1c --> R1d[200 OK]

    R2 --> R2a[Return { ok: true }]

    R3 --> R3a[Redirect 302 to /]
    R4 --> R4a[Redirect 302 to /]

    R5 --> R5a{Method POST?}
    R5a -->|No| R5b[405 Method Not Allowed]
    R5a -->|Yes| R5c[Decode JSON {start,target,depth}]
    R5c --> R5d{Valid payload?}
    R5d -->|No| R5e[400 Bad Request]
    R5d -->|Yes| R5f[Call SearchArtists(ctx, store, start, target, depth, 5, false)]
    R5f --> R5g{Error?}
    R5g -->|Yes| R5h[Return {message: err.Error()}]
    R5g -->|No| R5i{Message?}
    R5i -->|Yes| R5j[Return {message}]
    R5i -->|No| R5k[Map Steps -> [{from, track, to}]]
    R5k --> R5l[Return {start, target, hops, path}]

    E --> L[ListenAndServe(:PORT)]
```

## Endpoints

- GET /
  - Renders `templates/index.html`.
- GET /status
  - Health check: `{ "ok": true }`.
- GET /auth, GET /callback
  - OAuth stubs (currently redirect to `/`).
- POST /search
  - Accepts JSON: `{ start, target, depth }`.
  - Delegates to `SearchArtists` (see `http_search.go`).
  - Returns JSON: `{ start, target, hops, path: [{from, track, to}], message? }`.

## Notes

- Store is opened once at startup and migrated, then reused across requests.
- Port is read from `PORT` env var, defaults to `8080`.
- Error paths respond with appropriate HTTP status codes and/or `message` in JSON.
