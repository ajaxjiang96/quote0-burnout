FROM python:3.12-slim

WORKDIR /app

# Install tzdata and certificates for HTTPS
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure cache directory exists
RUN mkdir -p /app/tmp

# Healthcheck runs self-check (no push)
HEALTHCHECK --interval=5m --timeout=15s --start-period=30s --retries=3 \
    CMD python display.py --check || exit 1

CMD ["python", "display.py", "--interval", "5m"]
