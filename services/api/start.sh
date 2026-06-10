#!/bin/bash
set -e

# Start ARQ worker in background so it can process pipeline jobs
arq app.workers.settings.WorkerSettings &
WORKER_PID=$!

# Start uvicorn in foreground — keeping it alive keeps the Render service alive
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
