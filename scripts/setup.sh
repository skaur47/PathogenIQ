#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# PathogenIQ — Local development setup script
#
# Run once after cloning the repo:
#   chmod +x scripts/setup.sh && ./scripts/setup.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

echo "==> PathogenIQ setup"

# 1. Copy env file
if [ ! -f .env ]; then
  cp .env.example .env
  echo "✓ Created .env from .env.example (fill in API keys)"
else
  echo "  .env already exists, skipping"
fi

# 2. Start infrastructure services (not the API)
echo "==> Starting Docker services..."
docker compose up -d postgres neo4j qdrant redis

# 3. Wait for postgres
echo "==> Waiting for PostgreSQL..."
until docker compose exec postgres pg_isready -U pathogeniq -d pathogeniq > /dev/null 2>&1; do
  sleep 2
  echo "  still waiting..."
done
echo "✓ PostgreSQL ready"

# 4. Install Python dependencies locally (for IDE support)
if command -v pip &> /dev/null; then
  echo "==> Installing Python dependencies..."
  cd services/api
  pip install -e ".[dev]" --quiet
  cd ../..
  echo "✓ Dependencies installed"
fi

# 5. Run migrations
echo "==> Running Alembic migrations..."
docker compose run --rm api alembic upgrade head
echo "✓ Migrations applied"

echo ""
echo "==> Setup complete!"
echo "    Start the full stack:  docker compose up"
echo "    API docs:              http://localhost:8000/docs"
echo "    Neo4j browser:         http://localhost:7474"
echo "    Run tests:             cd services/api && pytest"
