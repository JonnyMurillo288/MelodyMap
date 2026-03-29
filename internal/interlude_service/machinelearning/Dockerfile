# internal/interlude_service/machinelearning/Dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN pip install --upgrade pip

# Install torch FIRST so failure is obvious
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Install dependencies first (cached layer if requirements.txt unchanged)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (respects .dockerignore)
COPY . .

EXPOSE 8000

# RUN_ENV=production disables --reload and adds workers
# Default: development mode with hot-reload
CMD if [ "$RUN_ENV" = "production" ]; then \
      uvicorn app:app --host 0.0.0.0 --port 8000 --workers 2 --timeout-keep-alive 120; \
    else \
      uvicorn app:app --host 0.0.0.0 --port 8000 --reload; \
    fi
