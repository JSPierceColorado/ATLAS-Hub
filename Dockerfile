FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 atlas
COPY atlas_hub ./atlas_hub
COPY main.py ./main.py
USER atlas

# One always-on background worker. No HTTP port and no Railway cron schedule.
CMD ["python", "main.py"]
