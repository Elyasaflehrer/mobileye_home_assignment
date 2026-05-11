FROM python:3.12-slim

# Run as a non-root user.
RUN useradd --create-home --shell /bin/bash app

WORKDIR /app

# Install dependencies first so app-code changes don't bust the deps cache.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code.
COPY app/ ./app/

USER app

EXPOSE 8080

# /health is a process-only liveness probe; no curl in the slim image.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
