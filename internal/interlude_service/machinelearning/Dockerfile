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

# Start script handles dev vs production mode
RUN echo '#!/bin/sh\n\
if [ "$RUN_ENV" = "production" ]; then\n\
  exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2 --timeout-keep-alive 120\n\
else\n\
  exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000} --reload\n\
fi' > /app/start.sh && chmod +x /app/start.sh

CMD ["/bin/sh", "/app/start.sh"]
