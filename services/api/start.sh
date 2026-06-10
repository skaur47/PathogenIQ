#!/bin/bash
set -e

# Run database migrations before starting — creates tables on first deploy,
# applies any new migrations on subsequent deploys.
alembic upgrade head

# Start ARQ worker in background so it can process pipeline jobs
arq app.workers.settings.WorkerSettings &

# Start uvicorn in foreground — keeping it alive keeps the Render service alive
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
