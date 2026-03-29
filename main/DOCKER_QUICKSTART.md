# Frontend Quickstart Guide - Go Web Server

This guide explains how to run the MelodyMap frontend (Go web server) that serves the web application and communicates with the ML backend.

## Prerequisites

- Go 1.24+ installed (or Docker)
- PostgreSQL database running with MusicBrainz data (default port: 5432)
- Spotify Developer credentials (for playlist creation feature)

## Quick Start

### Option 1: Run with Docker Compose (Recommended)

From the project root (`~/Desktop/MelodyMap`):

```bash
# Build and start only the frontend API service
docker-compose up api

# Or run in detached mode
docker-compose up -d api

# View logs
docker-compose logs -f api
```

The frontend will be available at `http://localhost:8080`.

### Option 2: Run with Go Directly (Local Development)

```bash
cd ~/Desktop/MelodyMap

# Install dependencies
go mod download

# Run the server
go run ./main
```

### Option 3: Build and Run Binary

```bash
cd ~/Desktop/MelodyMap

# Build the binary
go build -o melodymap_server ./main

# Run it
./melodymap_server
```

### Option 4: Run Standalone Docker

```bash
cd ~/Desktop/MelodyMap

# Build the image
docker build -t melodymap-api -f main/Dockerfile .

# Run the container
docker run -p 8080:8080 \
  -e PG_DSN="postgres://postgres:baseball162162@host.docker.internal:5432/musicbrainz_db?sslmode=disable" \
  -e RUN_ENV=docker \
  -v $(pwd)/static:/app/static \
  -v $(pwd)/templates:/app/templates \
  --add-host=host.docker.internal:host-gateway \
  melodymap-api
```

## Environment Configuration

### Local Development (.env.local)

Create a `.env.local` file in the project root:

```bash
# PostgreSQL
PG_DSN=postgres://postgres:baseball162162@localhost:5432/musicbrainz_db?sslmode=disable

# Application
PORT=8080
SDS_TOKEN_SECRET=your-secret-key-here

# Spotify OAuth (required for playlist creation)
SPOTIFY_CLIENT_ID=your-spotify-client-id
SPOTIFY_CLIENT_SECRET=your-spotify-client-secret
SPOTIFY_REDIRECT_URI=http://localhost:8080/auth/callback
SPOTIFY_TOKEN_PATH=spotify_token.json
```

### Docker Environment (.env.docker)

The `.env.docker` file is used when running in Docker:

```bash
PG_DSN=postgres://postgres:baseball162162@host.docker.internal:5432/musicbrainz_db?sslmode=disable
RUN_ENV=docker
PORT=8080
SDS_TOKEN_SECRET=your-secret-key-here

# Spotify OAuth
SPOTIFY_CLIENT_ID=your-spotify-client-id
SPOTIFY_CLIENT_SECRET=your-spotify-client-secret
SPOTIFY_REDIRECT_URI=https://your-domain.com/auth/callback
SPOTIFY_TOKEN_PATH=spotify_token.json
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PG_DSN` | PostgreSQL connection string | Required |
| `PORT` | Server port | `8080` |
| `RUN_ENV` | Runtime environment (`docker` or empty for local) | Empty |
| `SDS_TOKEN_SECRET` | Secret for anti-scrape token generation | Required |
| `SPOTIFY_CLIENT_ID` | Spotify OAuth client ID | Required for playlists |
| `SPOTIFY_CLIENT_SECRET` | Spotify OAuth client secret | Required for playlists |
| `SPOTIFY_REDIRECT_URI` | Spotify OAuth callback URL | Required for playlists |
| `SPOTIFY_TOKEN_PATH` | Path to store Spotify token | `spotify_token.json` |

## Web Routes

| Route | Method | Description |
|-------|--------|-------------|
| `/` | GET | Main application page (graph visualization) |
| `/ml` | GET | Machine learning page |
| `/static/*` | GET | Static assets (CSS, JS, images) |
| `/status` | GET | Health check endpoint |

## API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/search/start` | POST | Token | Start BFS artist search |
| `/api/search/status` | GET | Token | Get search job status |
| `/api/search/ticker` | GET | None | Get live search ticker data |
| `/lookup` | GET | Token | Lookup neighbor data for an artist |
| `/createPlaylist` | POST | Token | Create Spotify playlist from search path |
| `/auth/start` | GET | None | Begin Spotify OAuth flow |
| `/auth/callback` | GET | None | Spotify OAuth callback |
| `/ml/synth/artist` | POST | Token | ML synthetic artist prediction |

## Running the Full Stack

To run both frontend and ML backend together:

```bash
cd ~/Desktop/MelodyMap
docker-compose up
```

This starts:
- **api** service (Go frontend) on port `8080`
- **ml** service (Python ML backend) on port `8000`

The frontend communicates with the ML backend at `http://ml:8000` (internal Docker network) or `http://localhost:8000` (local development).

## Project Structure

```
MelodyMap/
├── main/                    # Go web server
│   ├── main.go              # Entry point, routes
│   ├── Dockerfile           # Production Docker build
│   ├── graph_builder.go     # Graph construction logic
│   ├── search_handlers.go   # Search API handlers
│   └── machine_learning_handlers.go  # ML API handlers
├── internal/                # Internal packages
│   ├── auth/                # Authentication & OAuth
│   ├── search/              # BFS search logic
│   ├── jobs/                # Background job management
│   └── secret/              # Secret management
├── templates/               # HTML templates
│   ├── graph_test.html      # Main UI
│   └── ml_page.html         # ML page UI
├── static/                  # Static assets
├── spotify/                 # Spotify API integration
├── .env.local               # Local environment config
├── .env.docker              # Docker environment config
├── docker-compose.yml       # Docker compose config
└── go.mod                   # Go module definition
```

## Verifying the Service

```bash
# Health check
curl http://localhost:8080/status
# Expected: {"ok":true}

# Open in browser
open http://localhost:8080
```

## Spotify OAuth Setup

To enable playlist creation:

1. Create a Spotify Developer app at https://developer.spotify.com/dashboard
2. Add your redirect URI (e.g., `http://localhost:8080/auth/callback`)
3. Copy Client ID and Client Secret to your `.env.local` file
4. Restart the server

Users will be prompted to authorize via Spotify when creating a playlist.

## Troubleshooting

### Database Connection Failed
```
Error: could not connect to server
```
**Solution:** Ensure PostgreSQL is running and `PG_DSN` is correct. For Docker, use `host.docker.internal` instead of `localhost`.

### Static Files Not Loading
```
404 on /static/* routes
```
**Solution:** Ensure you're running from the project root, or that volumes are mounted correctly in Docker.

### Token Generation Failed
```
token generation failed
```
**Solution:** Set the `SDS_TOKEN_SECRET` environment variable.

### Spotify Auth Issues
```
auth_required response on /createPlaylist
```
**Solution:** User needs to authenticate via `/auth/start`. Ensure Spotify credentials are configured.

### Port Already in Use
```bash
# Find what's using port 8080
sudo ss -tulpn | grep ':8080'

# Kill the process
kill -9 <PID>
```

## Development Tips

1. **Hot Reload**: Use `air` or `reflex` for auto-reload during development:
   ```bash
   go install github.com/cosmtrek/air@latest
   air
   ```

2. **Debug Mode**: Add logging by checking stdout/stderr

3. **Template Changes**: Templates are re-parsed on each request, so changes are immediate

## Stopping the Service

```bash
# If using docker-compose
docker-compose down

# If running Go directly
Ctrl+C

# If using standalone docker
docker stop <container_id>
```
