# PathogenIQ

Real-time infectious disease intelligence and therapeutic discovery platform.

> All AI-generated outputs require expert review before clinical or public health application.

## Architecture

```
PathogenIQ/
├── services/
│   └── api/                 # FastAPI backend (Phase 1 ✓)
│       ├── app/
│       │   ├── main.py      # FastAPI app + lifespan
│       │   ├── config.py    # Pydantic settings
│       │   ├── api/v1/      # HTTP endpoints
│       │   ├── db/          # SQLAlchemy models + Alembic migrations
│       │   ├── repositories/ # Database access layer
│       │   └── core/        # Logging, utilities
│       └── tests/
├── shared/                  # Shared Pydantic schemas
├── scripts/                 # Dev helper scripts
├── docker-compose.yml       # Local dev stack
└── .env.example
```

## Stack

| Layer | Technology |
|---|---|
| API | FastAPI + uvicorn |
| Database | PostgreSQL 16 + SQLAlchemy 2.0 async |
| Knowledge Graph | Neo4j 5 |
| Vector DB | Qdrant |
| Cache / Queue | Redis 7 |
| Migrations | Alembic (async) |
| AI Agents | LangGraph (Phase 3) |
| Frontend | Next.js (Phase 5) |

## Quick Start

```bash
# 1. Setup (first time only)
chmod +x scripts/setup.sh && ./scripts/setup.sh

# 2. Start everything
docker compose up

# 3. Open API docs
open http://localhost:8000/docs

# 4. Run tests
cd services/api && pytest -v
```

## Agents (Phase 3)

| Agent | Role |
|---|---|
| Sentinel | Feed aggregation, outbreak detection |
| Scholar | PubMed/bioRxiv literature synthesis |
| Mechanica | Mutation analysis, immune escape |
| Intervention | Therapeutic candidate identification |
| GraphMind | Neo4j knowledge graph construction |
| Verifier | Citation verification, hallucination prevention |
| Frontier | Research gap detection |
| Atlas | Executive synthesis, risk briefings |

## Development Phases

- **Phase 1** ✓ — Backend foundation: FastAPI, PostgreSQL, health checks, models, repositories
- **Phase 2** — Data ingestion: Sentinel agent, PubMed/CDC/WHO collectors, background tasks
- **Phase 3** — AI layer: LangGraph agents, Claude integration, RAG with Qdrant
- **Phase 4** — Knowledge graph: Neo4j relationships, graph queries
- **Phase 5** — Frontend: Next.js dashboard, real-time alerts, graph visualization
- **Phase 6** — Production: CI/CD, monitoring, Kubernetes deployment
