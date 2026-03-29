# Docker Quickstart Guide - ML Backend Service

This guide explains how to run the ML backend service using Docker to provide API endpoints for the frontend.

## Prerequisites

- Docker and Docker Compose installed
- PostgreSQL database running with MusicBrainz data (default port: 5432)
- The ML model artifacts in `./feature_engineering/` directory

## Quick Start

### Option 1: Run with Docker Compose (Recommended)

From the project root (`~/Desktop/MelodyMap`):

```bash
# Build and start only the ML service
docker-compose up ml

# Or run in detached mode
docker-compose up -d ml

# View logs
docker-compose logs -f ml
```

The ML service will be available at `http://localhost:8000`.

### Option 2: Run Standalone Docker

From the `machinelearning` directory:

```bash
cd ~/Desktop/MelodyMap/internal/interlude_service/machinelearning

# Build the image
docker build -t melodymap-ml .

# Run the container
docker run -p 8000:8000 \
  -e PG_DSN="postgres://postgres:baseball162162@host.docker.internal:5432/musicbrainz_db?sslmode=disable" \
  --add-host=host.docker.internal:host-gateway \
  -v $(pwd):/app \
  melodymap-ml
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PG_DSN` | PostgreSQL connection string | `postgres://postgres:baseball162162@localhost:5432/musicbrainz_db?sslmode=disable` |
| `DATA_DIR` | Directory for data files | `/tmp` |
| `OUTPUT_DIR` | Directory for output files | `/tmp` |
| `MODEL_ENGINEERING_DIR` | Directory for model artifacts | `./feature_engineering` |

## API Endpoints

Once running, the service exposes these endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/ml/predict/artist-link` | POST | Predict collaboration probability between two artists |
| `/ml/predict/artist-neighbors` | POST | Get predicted collaboration neighbors for an artist |
| `/ml/generate/tracks` | POST | Generate synthetic track features for artist pair |

### Example Requests

**Predict Artist Link:**
```bash
curl -X POST http://localhost:8000/ml/predict/artist-link \
  -H "Content-Type: application/json" \
  -d '{
    "src_artist_id": "some-mbid-uuid",
    "dst_artist_id": "another-mbid-uuid",
    "model_version": "logit_v1"
  }'
```

**Get Artist Neighbors:**
```bash
curl -X POST http://localhost:8000/ml/predict/artist-neighbors \
  -H "Content-Type: application/json" \
  -d '{
    "src_artist_id": "some-mbid-uuid",
    "limit": 25,
    "model_version": "logit_v1"
  }'
```

**Generate Synthetic Tracks:**
```bash
curl -X POST http://localhost:8000/ml/generate/tracks \
  -H "Content-Type: application/json" \
  -d '{
    "src_artist_id": "some-mbid-uuid",
    "dst_artist_id": "another-mbid-uuid",
    "limit": 5,
    "model_version": "cvae_v1"
  }'
```

## Running Both Frontend and ML Backend

To run the full stack:

```bash
cd ~/Desktop/MelodyMap
docker-compose up
```

This starts:
- **api** service (Go frontend) on port `8080`
- **ml** service (Python ML backend) on port `8000`

## Verifying the Service

Check if the service is running:

```bash
# Health check via FastAPI docs
curl http://localhost:8000/docs

# Or check with a simple request
curl http://localhost:8000/openapi.json
```

## Troubleshooting

### Database Connection Failed
```
Error: could not connect to server
```
**Solution:** Ensure PostgreSQL is running and accessible. If running in Docker, use `host.docker.internal` instead of `localhost` in the connection string.

### Model File Not Found
```
FileNotFoundError: Model file not found
```
**Solution:** Ensure the model artifacts exist in `./feature_engineering/logit_model_v1.joblib`. Run the pipeline first if needed:
```bash
python run_pipeline.py --train-link-model
```

### Port Already in Use
```
Error: port 8000 is already in use
```
**Solution:** Stop any existing service on port 8000, or change the port mapping:

```bash
sudo ss -tulpn | grep ':8000'
```
then find the PID and kill the application using it

```bash
sudo kill -9 1234
```

```bash
docker run -p 8001:8000 ...
```

### Container Can't Reach Host Database
**Solution:** Use `--add-host=host.docker.internal:host-gateway` flag or configure Docker networking appropriately for your OS.

## Development Mode

For development with hot-reloading, the docker-compose.yml already mounts the source directory as a volume. Changes to Python files will require a container restart:

```bash
docker-compose restart ml
```

## Stopping the Service

```bash
# If using docker-compose
docker-compose down

# If using standalone docker
docker stop <container_id>
```
